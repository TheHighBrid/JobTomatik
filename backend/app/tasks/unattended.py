"""Second fail-closed chokepoint for scheduled application submissions."""

import logging
from datetime import datetime, timezone

from celery.exceptions import Retry

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.application import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
)
from app.models.certification import ShadowRunSession
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.application_integrity import install_closed_application_task_gate
from app.services.application_state import create_manual_review_task
from app.services.certification_scale import ensure_aware
from app.services.full_stack_shadow import (
    ACTIVE_SESSION_STATES,
    finalize_shadow_session,
)
from app.services.supervised_submission_integration import (
    install_supervised_submission_task_gate,
)
from app.services.unattended_policy import (
    evaluate_unattended_job_policy,
    shadow_dry_run_policy_context,
)


logger = logging.getLogger(__name__)

install_supervised_submission_task_gate()
install_closed_application_task_gate()


_CAMPAIGN_FAILING_SHADOW_ERRORS = frozenset(
    {
        "shadow_worker_session_mismatch",
        "shadow_worker_requires_dry_run",
        "shadow_worker_requires_real_submission_disabled",
        "shadow_worker_settle_deadline_missing",
        "shadow_worker_settle_deadline_expired",
        "shadow_worker_final_submit_flag_changed",
        "shadow_worker_session_invariants_invalid",
    }
)


def _shadow_application_context(
    db,
    app: Application,
    *,
    requested_shadow_session_id: int | None,
    dry_run: bool,
) -> tuple[int | None, str | None]:
    """Derive shadow authority from durable evidence, never from task kwargs alone."""

    created_event = (
        db.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == app.id,
            ApplicationEvent.event_type == "application_created",
        )
        .order_by(ApplicationEvent.created_at.desc(), ApplicationEvent.id.desc())
        .first()
    )
    payload = dict(created_event.payload or {}) if created_event is not None else {}
    event_is_shadow = payload.get("source") == "full_stack_shadow_scheduler"

    if not event_is_shadow and requested_shadow_session_id is None:
        return None, None
    if not event_is_shadow:
        return None, "shadow_worker_application_not_correlated"

    try:
        event_shadow_session_id = int(payload.get("shadow_session_id"))
    except (TypeError, ValueError):
        return None, "shadow_worker_application_not_correlated"
    if event_shadow_session_id <= 0:
        return None, "shadow_worker_application_not_correlated"

    if requested_shadow_session_id is not None:
        try:
            requested = int(requested_shadow_session_id)
        except (TypeError, ValueError):
            return event_shadow_session_id, "shadow_worker_session_mismatch"
        if requested != event_shadow_session_id:
            return event_shadow_session_id, "shadow_worker_session_mismatch"

    if payload.get("dry_run") is not True or dry_run is not True:
        return event_shadow_session_id, "shadow_worker_requires_dry_run"

    if get_settings().allow_real_application_submit is not False:
        return event_shadow_session_id, "shadow_worker_requires_real_submission_disabled"

    session = (
        db.query(ShadowRunSession)
        .filter(
            ShadowRunSession.id == event_shadow_session_id,
            ShadowRunSession.user_id == app.user_id,
        )
        .first()
    )
    if session is None:
        return event_shadow_session_id, "shadow_worker_session_inactive"
    if session.stop_requested or session.status == "stopping":
        return event_shadow_session_id, "shadow_worker_stop_requested"
    if session.status not in ACTIVE_SESSION_STATES:
        return event_shadow_session_id, "shadow_worker_session_inactive"

    settle_deadline = ensure_aware(session.settle_deadline_at)
    current = datetime.now(timezone.utc)
    if settle_deadline is None:
        return event_shadow_session_id, "shadow_worker_settle_deadline_missing"
    if current >= settle_deadline:
        return event_shadow_session_id, "shadow_worker_settle_deadline_expired"

    if session.final_submit_allowed is not False:
        return event_shadow_session_id, "shadow_worker_final_submit_flag_changed"

    invariants = dict((session.configuration_snapshot or {}).get("invariants") or {})
    if (
        invariants.get("dry_run_required") is not True
        or invariants.get("real_submission_must_remain_disabled") is not True
        or invariants.get("final_submit_allowed") is not False
    ):
        return event_shadow_session_id, "shadow_worker_session_invariants_invalid"

    return event_shadow_session_id, None


def _block_shadow_worker(
    db,
    *,
    app: Application,
    job: Job,
    user: User,
    dry_run: bool,
    reason_code: str,
    shadow_session_id: int | None,
) -> dict:
    """Retain a worker block and make pre-browser shadow failures evidence-fatal."""

    reason = f"Shadow application worker blocked: {reason_code}"
    result = {
        "success": False,
        "dry_run": dry_run,
        "requires_manual_review": True,
        "error": reason_code,
        "policy_decision": {
            "allowed": False,
            "code": reason_code,
            "reason": reason,
            "metadata": {
                "shadow_worker": True,
                "shadow_session_id": shadow_session_id,
            },
        },
        "log": [
            {
                "action": "shadow_worker_safety_blocked",
                "reason_code": reason_code,
                "reason": reason,
                "shadow_session_id": shadow_session_id,
                "ts": datetime.utcnow().isoformat(),
            }
        ],
    }
    app.status = ApplicationStatus.pending
    app.automation_log = result["log"]
    create_manual_review_task(
        db,
        app,
        ManualReviewReason.safety_gate_blocked,
        reason,
        details={
            "shadow_worker": True,
            "reason_code": reason_code,
            "shadow_session_id": shadow_session_id,
        },
        blocking_url=job.url,
    )
    db.add(
        ApplicationEvent(
            application_id=app.id,
            event_type="shadow_worker_safety_blocked",
            from_state=str(app.automation_state or ""),
            to_state=str(app.automation_state or ""),
            payload={
                "source": "full_stack_shadow_scheduler",
                "dry_run": dry_run,
                "shadow_session_id": shadow_session_id,
                "reason_code": reason_code,
            },
        )
    )
    db.add(
        Notification(
            user_id=user.id,
            type=NotificationType.system,
            title=f"Shadow action blocked: {job.title}",
            message=reason,
            data={
                "job_id": job.id,
                "application_id": app.id,
                "reason": reason_code,
                "shadow_worker": True,
                "shadow_session_id": shadow_session_id,
            },
        )
    )
    db.flush()

    campaign_failing = (
        reason_code in _CAMPAIGN_FAILING_SHADOW_ERRORS
        or reason_code.startswith("shadow_worker_policy_blocked:")
    )
    if shadow_session_id is not None and campaign_failing:
        session = (
            db.query(ShadowRunSession)
            .filter(
                ShadowRunSession.id == int(shadow_session_id),
                ShadowRunSession.user_id == user.id,
            )
            .with_for_update()
            .first()
        )
        if session is not None and session.status in ACTIVE_SESSION_STATES:
            finalize_shadow_session(
                db,
                session,
                requested_status="failed",
                failure_reason=f"shadow_worker_safety_invariant:{reason_code}",
            )

    db.commit()
    logger.warning("Blocked shadow application %s: %s", app.id, reason_code)
    return result


@celery_app.task(
    bind=True,
    name="app.tasks.unattended.submit_unattended_application_task",
    queue="applications",
    max_retries=None,
)
def submit_unattended_application_task(
    self,
    application_id: int,
    dry_run: bool = True,
    shadow_session_id: int | None = None,
):
    """Re-evaluate live policy immediately before the normal submit worker."""
    db = SessionLocal()
    try:
        app = (
            db.query(Application)
            .filter(Application.id == application_id)
            .with_for_update()
            .first()
        )
        if not app:
            return {"error": "Application not found"}
        job = db.query(Job).filter(Job.id == app.job_id).first()
        user = db.query(User).filter(User.id == app.user_id).first()
        if not job or not user:
            return {"error": "Missing job or user"}

        effective_shadow_session_id, shadow_error = _shadow_application_context(
            db,
            app,
            requested_shadow_session_id=shadow_session_id,
            dry_run=dry_run,
        )
        if shadow_error is not None:
            return _block_shadow_worker(
                db,
                app=app,
                job=job,
                user=user,
                dry_run=dry_run,
                reason_code=shadow_error,
                shadow_session_id=effective_shadow_session_id,
            )

        if effective_shadow_session_id is not None:
            with shadow_dry_run_policy_context(
                shadow_session_id=effective_shadow_session_id,
                dry_run=True,
                application_id=app.id,
            ):
                decision = evaluate_unattended_job_policy(db, user, job)
        else:
            decision = evaluate_unattended_job_policy(db, user, job)

        if not decision.allowed:
            if effective_shadow_session_id is not None:
                return _block_shadow_worker(
                    db,
                    app=app,
                    job=job,
                    user=user,
                    dry_run=dry_run,
                    reason_code=f"shadow_worker_policy_blocked:{decision.code}",
                    shadow_session_id=effective_shadow_session_id,
                )

            if decision.code == "operator_paused":
                # A pause is a temporary queue hold, not a policy failure.  Leave
                # the application and its review state untouched and keep retrying
                # until an operator resumes (or revokes the queued application).
                db.rollback()
                logger.info(
                    "Deferred unattended application %s while operator pause is active",
                    application_id,
                )
                raise self.retry(countdown=60)

            result = {
                "success": False,
                "dry_run": dry_run,
                "requires_manual_review": True,
                "error": decision.reason,
                "policy_decision": decision.to_dict(),
                "log": [
                    {
                        "action": "unattended_policy_blocked",
                        "reason_code": decision.code,
                        "reason": decision.reason,
                        "ts": datetime.utcnow().isoformat(),
                    }
                ],
            }
            app.status = ApplicationStatus.pending
            app.automation_log = result["log"]
            create_manual_review_task(
                db,
                app,
                ManualReviewReason.safety_gate_blocked,
                decision.reason,
                details={"unattended": True, **decision.to_dict()},
                blocking_url=job.url,
            )
            db.add(
                Notification(
                    user_id=user.id,
                    type=NotificationType.system,
                    title=f"Unattended action blocked: {job.title}",
                    message=decision.reason,
                    data={
                        "job_id": job.id,
                        "application_id": app.id,
                        "reason": decision.code,
                    },
                )
            )
            db.commit()
            logger.warning(
                "Blocked unattended application %s: %s",
                application_id,
                decision.code,
            )
            return result
    except Retry:
        raise
    except Exception as exc:
        logger.exception("submit_unattended_application_task failed")
        db.rollback()
        raise self.retry(exc=exc, countdown=60, max_retries=2)
    finally:
        db.close()

    from app.tasks.applications import submit_application_task

    return submit_application_task.run(application_id, dry_run=dry_run)
