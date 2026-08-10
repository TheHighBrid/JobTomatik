"""Second fail-closed chokepoint for scheduled application submissions."""

import logging
from datetime import datetime

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
from app.services.full_stack_shadow import ACTIVE_SESSION_STATES
from app.services.supervised_submission_integration import (
    install_supervised_submission_task_gate,
)
from app.services.unattended_policy import (
    evaluate_unattended_job_policy,
    shadow_dry_run_policy_context,
)


logger = logging.getLogger(__name__)

# Celery imports this module before consuming application-queue work. Installing
# here keeps the worker fail-closed even when a local PRoot pool omits lifecycle
# signals. The closed-record gate must remain outside the supervised approval gate.
install_supervised_submission_task_gate()
install_closed_application_task_gate()


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
            return None, "shadow_worker_session_mismatch"
        if requested != event_shadow_session_id:
            return None, "shadow_worker_session_mismatch"

    # The persisted event and the current task invocation must both say dry-run.
    if payload.get("dry_run") is not True or dry_run is not True:
        return None, "shadow_worker_requires_dry_run"

    # This is checked again here even though Phase 11 preflight and the scheduler
    # already enforce it. A delayed/replayed task must fail closed if configuration
    # changed after it was queued.
    if get_settings().allow_real_application_submit is not False:
        return None, "shadow_worker_requires_real_submission_disabled"

    session = (
        db.query(ShadowRunSession)
        .filter(
            ShadowRunSession.id == event_shadow_session_id,
            ShadowRunSession.user_id == app.user_id,
        )
        .first()
    )
    if session is None or session.status not in ACTIVE_SESSION_STATES:
        return None, "shadow_worker_session_inactive"
    if session.final_submit_allowed is not False:
        return None, "shadow_worker_final_submit_flag_changed"

    invariants = dict((session.configuration_snapshot or {}).get("invariants") or {})
    if (
        invariants.get("dry_run_required") is not True
        or invariants.get("real_submission_must_remain_disabled") is not True
        or invariants.get("final_submit_allowed") is not False
    ):
        return None, "shadow_worker_session_invariants_invalid"

    return event_shadow_session_id, None


def _block_shadow_worker(
    db,
    *,
    app: Application,
    job: Job,
    user: User,
    dry_run: bool,
    reason_code: str,
) -> dict:
    reason = f"Shadow application worker blocked by invariant: {reason_code}"
    result = {
        "success": False,
        "dry_run": dry_run,
        "requires_manual_review": True,
        "error": reason_code,
        "policy_decision": {
            "allowed": False,
            "code": reason_code,
            "reason": reason,
            "metadata": {"shadow_worker": True},
        },
        "log": [
            {
                "action": "shadow_worker_safety_blocked",
                "reason_code": reason_code,
                "reason": reason,
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
        details={"shadow_worker": True, "reason_code": reason_code},
        blocking_url=job.url,
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
            },
        )
    )
    db.commit()
    logger.warning("Blocked shadow application %s: %s", app.id, reason_code)
    return result


@celery_app.task(
    bind=True,
    name="app.tasks.unattended.submit_unattended_application_task",
    queue="applications",
)
def submit_unattended_application_task(
    self,
    application_id: int,
    dry_run: bool = True,
    shadow_session_id: int | None = None,
):
    """Re-evaluate live policy immediately before the normal submit worker.

    Shadow work derives its session from the durable application event and verifies
    dry-run + global no-submit + active-session invariants before the narrow maturity
    exception is even visible to policy evaluation.
    """
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
            )

        if effective_shadow_session_id is not None:
            with shadow_dry_run_policy_context(
                shadow_session_id=effective_shadow_session_id,
                dry_run=True,
            ):
                decision = evaluate_unattended_job_policy(db, user, job)
        else:
            decision = evaluate_unattended_job_policy(db, user, job)

        if not decision.allowed:
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
    except Exception as exc:
        logger.exception("submit_unattended_application_task failed")
        db.rollback()
        raise self.retry(exc=exc, countdown=60, max_retries=2)
    finally:
        db.close()

    from app.tasks.applications import submit_application_task

    return submit_application_task.run(application_id, dry_run=dry_run)
