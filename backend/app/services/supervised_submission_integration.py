"""Defense-in-depth worker gate for platform-scoped supervised submissions."""

from __future__ import annotations

from typing import Optional

from app.models.application import Application, ApplicationAutomationState, ApplicationEvent
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.models.user import User
from app.services.application_state import normalize_state
from app.services.operations_policy import platform_key_for_url
from app.services.submission_integrity import (
    claim_submission_attempt,
    finalize_submission_attempt,
    submission_attempt_replay_result,
)
from app.services.supervised_platforms import get_supervised_platform_policy
from app.services.supervised_runtime import supervised_target_scope
from app.services.supervised_submission import (
    SupervisedSubmissionApprovalError,
    validate_supervised_approval,
)
from app.services.supervised_target_identity import (
    persist_supervised_target_metadata,
    resolve_supervised_target_metadata,
)


_INSTALLED = False
_ORIGINAL_RUN = None


def _target_url(job: Job) -> str:
    raw = dict(job.raw_data or {})
    return str(raw.get("selected_apply_url") or job.url or "").strip()


def _record_block(db, application, user, job, *, platform, approval_reference, reason):
    payload = {
        "approval_reference": approval_reference,
        "platform": platform,
        "reason": reason[:500],
    }
    recent = db.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == application.id,
        ApplicationEvent.event_type == "supervised_submission_blocked",
    ).order_by(ApplicationEvent.id.desc()).limit(10).all()
    if any(
        (item.payload or {}).get("approval_reference") == approval_reference
        and (item.payload or {}).get("platform") == platform
        and (item.payload or {}).get("reason") == payload["reason"]
        for item in recent
    ):
        return
    db.add(ApplicationEvent(
        application_id=application.id,
        event_type="supervised_submission_blocked",
        from_state=application.automation_state,
        to_state=application.automation_state,
        payload=payload,
    ))
    db.add(Notification(
        user_id=user.id,
        type=NotificationType.system,
        title=f"Supervised submission blocked: {job.title}",
        message=reason[:1000],
        data={
            "application_id": application.id,
            "job_id": job.id,
            "platform": platform,
            "approval_reference": approval_reference,
            "reason": "supervised_approval_blocked",
        },
    ))


def _attempt_for_reference(db, application_id, attempt_reference):
    if not attempt_reference:
        return None
    return db.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application_id,
        SubmissionAttempt.reference == attempt_reference,
    ).first()


def _attempt_for_approval(db, application_id, approval_reference):
    return db.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application_id,
        SubmissionAttempt.approval_reference == approval_reference,
    ).order_by(SubmissionAttempt.id.desc()).first()


def _blocked_result(
    application,
    *,
    platform,
    reason,
    approval_reference=None,
    attempt_reference=None,
    approval_required=True,
):
    return {
        "success": False,
        "dry_run": False,
        "application_id": application.id,
        "requires_manual_review": False,
        "approval_required": approval_required,
        "attempt_required": True,
        "approval_reference": approval_reference,
        "attempt_reference": attempt_reference,
        "automatic_retry_allowed": False,
        "supervised_platform_supported": bool(platform),
        "platform": platform,
        "error": reason,
    }


def _finalize_after_result(application_tasks, application_id, attempt_reference, result):
    db = application_tasks.SessionLocal()
    try:
        attempt = _attempt_for_reference(db, application_id, attempt_reference)
        application = db.query(Application).filter(Application.id == application_id).first()
        if not attempt or not application:
            return
        state = normalize_state(application.automation_state)
        if state in {
            ApplicationAutomationState.submitted.value,
            ApplicationAutomationState.confirmed.value,
        }:
            status = SubmissionAttemptStatus.succeeded
        elif state == ApplicationAutomationState.submission_uncertain.value:
            status = SubmissionAttemptStatus.uncertain
        elif isinstance(result, dict) and (
            result.get("requires_manual_review") or result.get("success")
        ):
            status = SubmissionAttemptStatus.uncertain
        else:
            status = SubmissionAttemptStatus.failed
        finalize_submission_attempt(
            db,
            attempt,
            status=status,
            result={
                "application_state": state,
                "success": bool(result.get("success")) if isinstance(result, dict) else False,
                "requires_manual_review": bool(result.get("requires_manual_review"))
                if isinstance(result, dict)
                else False,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _finalize_uncertain(application_tasks, application_id, attempt_reference, exc):
    db = application_tasks.SessionLocal()
    try:
        attempt = _attempt_for_reference(db, application_id, attempt_reference)
        if attempt:
            finalize_submission_attempt(
                db,
                attempt,
                status=SubmissionAttemptStatus.uncertain,
                result={
                    "automatic_retry_allowed": False,
                    "reason": "worker_exception_after_attempt_claim",
                    "exception": f"{type(exc).__name__}: {str(exc)[:300]}",
                },
            )
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def install_supervised_submission_task_gate() -> None:
    """Require one exact approval and one durable attempt for every live worker run."""

    global _INSTALLED, _ORIGINAL_RUN
    if _INSTALLED:
        return

    from app.tasks import applications as application_tasks

    task = application_tasks.submit_application_task
    _ORIGINAL_RUN = task.run

    def wrapped_run(
        application_id: int,
        dry_run: bool = True,
        approval_reference: Optional[str] = None,
        attempt_reference: Optional[str] = None,
    ):
        if dry_run:
            return _ORIGINAL_RUN(application_id, dry_run=True)

        db = application_tasks.SessionLocal()
        target_metadata = None
        platform = ""
        consumed_reference = approval_reference
        try:
            application = db.query(Application).filter(
                Application.id == application_id
            ).with_for_update().first()
            if not application:
                return {"error": "Application not found"}
            job = db.query(Job).filter(Job.id == application.job_id).first()
            user = db.query(User).filter(User.id == application.user_id).first()
            if not job or not user:
                return {"error": "Missing job or user"}

            platform = platform_key_for_url(_target_url(job))
            policy = get_supervised_platform_policy(platform)
            if policy is None:
                reason = (
                    "Live submission is blocked because this ATS platform is not "
                    f"registered for supervised submission: {platform or 'generic'}."
                )
                _record_block(
                    db,
                    application,
                    user,
                    job,
                    platform=platform,
                    approval_reference=approval_reference,
                    reason=reason,
                )
                db.commit()
                return _blocked_result(
                    application,
                    platform=platform,
                    reason=reason,
                    approval_reference=approval_reference,
                    attempt_reference=attempt_reference,
                    approval_required=False,
                )

            if not approval_reference:
                reason = (
                    f"{policy.display_name} live submission requires a short-lived, "
                    "exact-payload approval from the supervised submission API."
                )
                _record_block(
                    db,
                    application,
                    user,
                    job,
                    platform=platform,
                    approval_reference=None,
                    reason=reason,
                )
                db.commit()
                return _blocked_result(
                    application,
                    platform=platform,
                    reason=reason,
                )

            approval = db.query(SubmissionApproval).filter(
                SubmissionApproval.application_id == application.id,
                SubmissionApproval.user_id == user.id,
                SubmissionApproval.reference == approval_reference,
            ).first()
            if not approval:
                reason = "Submission approval not found"
                _record_block(
                    db,
                    application,
                    user,
                    job,
                    platform=platform,
                    approval_reference=approval_reference,
                    reason=reason,
                )
                db.commit()
                return _blocked_result(
                    application,
                    platform=platform,
                    reason=reason,
                    approval_reference=approval_reference,
                )

            # Refresh and validate approval payload before checking the queue attempt.
            # This preserves truthful drift/revocation reporting for stale direct calls,
            # while a valid approval still cannot reach a browser without a reservation.
            if policy.requires_exact_target_identity:
                target_metadata = application_tasks._run_async(
                    resolve_supervised_target_metadata(job)
                )
                if target_metadata:
                    persist_supervised_target_metadata(job, target_metadata)
            try:
                validate_supervised_approval(
                    db,
                    application,
                    user,
                    job,
                    reference=approval_reference,
                    consume=False,
                    target_metadata=target_metadata,
                )
            except SupervisedSubmissionApprovalError as exc:
                reason = str(exc)
                _record_block(
                    db,
                    application,
                    user,
                    job,
                    platform=platform,
                    approval_reference=approval_reference,
                    reason=reason,
                )
                db.commit()
                return _blocked_result(
                    application,
                    platform=platform,
                    reason=reason,
                    approval_reference=approval_reference,
                    attempt_reference=attempt_reference,
                )

            if not attempt_reference:
                reserved = _attempt_for_approval(db, application.id, approval_reference)
                attempt_reference = reserved.reference if reserved else None
            if not attempt_reference:
                reason = "No durable submission attempt was reserved before queue publication."
                _record_block(
                    db,
                    application,
                    user,
                    job,
                    platform=platform,
                    approval_reference=approval_reference,
                    reason=reason,
                )
                db.commit()
                return _blocked_result(
                    application,
                    platform=platform,
                    reason=reason,
                    approval_reference=approval_reference,
                )

            claimed_attempt, claimed = claim_submission_attempt(
                db,
                application,
                approval,
                attempt_reference=attempt_reference,
            )
            if not claimed:
                db.commit()
                if claimed_attempt:
                    return submission_attempt_replay_result(claimed_attempt)
                return {
                    "success": False,
                    "idempotent": True,
                    "duplicate_final_action_prevented": True,
                    "automatic_retry_allowed": False,
                    "application_id": application.id,
                    "attempt_reference": attempt_reference,
                    "error": "Submission attempt reservation is missing or no longer claimable.",
                }

            if policy.requires_exact_target_identity and (
                not target_metadata or not target_metadata.get("verified")
            ):
                blockers = list((target_metadata or {}).get("blockers") or [])
                reason = (
                    f"{policy.display_name} live submission target verification failed "
                    "before approval consumption: "
                    + ", ".join(blockers or ["exact_target_identity_unverified"])
                )
                finalize_submission_attempt(
                    db,
                    claimed_attempt,
                    status=SubmissionAttemptStatus.blocked,
                    result={"reason": reason, "automatic_retry_allowed": False},
                )
                _record_block(
                    db,
                    application,
                    user,
                    job,
                    platform=platform,
                    approval_reference=approval_reference,
                    reason=reason,
                )
                db.commit()
                return _blocked_result(
                    application,
                    platform=platform,
                    reason=reason,
                    approval_reference=approval_reference,
                    attempt_reference=attempt_reference,
                )

            try:
                approval = validate_supervised_approval(
                    db,
                    application,
                    user,
                    job,
                    reference=approval_reference,
                    consume=True,
                    target_metadata=target_metadata,
                )
            except SupervisedSubmissionApprovalError as exc:
                reason = str(exc)
                finalize_submission_attempt(
                    db,
                    claimed_attempt,
                    status=SubmissionAttemptStatus.blocked,
                    result={"reason": reason, "automatic_retry_allowed": False},
                )
                _record_block(
                    db,
                    application,
                    user,
                    job,
                    platform=platform,
                    approval_reference=approval_reference,
                    reason=reason,
                )
                db.commit()
                return _blocked_result(
                    application,
                    platform=platform,
                    reason=reason,
                    approval_reference=approval_reference,
                    attempt_reference=attempt_reference,
                )

            db.commit()
            consumed_reference = approval.reference
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            with supervised_target_scope(target_metadata):
                result = _ORIGINAL_RUN(application_id, dry_run=False)
        except Exception as exc:
            _finalize_uncertain(application_tasks, application_id, attempt_reference, exc)
            return {
                "success": False,
                "dry_run": False,
                "application_id": application_id,
                "approval_reference": consumed_reference,
                "attempt_reference": attempt_reference,
                "attempt_status": SubmissionAttemptStatus.uncertain.value,
                "automatic_retry_allowed": False,
                "duplicate_final_action_prevented": True,
                "requires_manual_review": True,
                "error": "The live worker failed after claiming the one-time attempt; automatic final-action retry is suppressed.",
            }

        _finalize_after_result(application_tasks, application_id, attempt_reference, result)
        if isinstance(result, dict):
            result.setdefault("approval_reference", consumed_reference)
            result.setdefault("attempt_reference", attempt_reference)
            result.setdefault("automatic_retry_allowed", False)
            result.setdefault("supervised_pilot", True)
            result.setdefault("supervised_platform", platform)
        return result

    task.run = wrapped_run
    _INSTALLED = True


__all__ = ["install_supervised_submission_task_gate"]
