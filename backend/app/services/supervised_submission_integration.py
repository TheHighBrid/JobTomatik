"""Defense-in-depth worker gate for platform-scoped supervised submissions."""

from __future__ import annotations

from typing import Optional

from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.operations_policy import platform_key_for_url
from app.services.supervised_platforms import get_supervised_platform_policy
from app.services.supervised_submission import (
    SupervisedSubmissionApprovalError,
    validate_supervised_approval,
)


_INSTALLED = False
_ORIGINAL_RUN = None


def _target_url(job: Job) -> str:
    raw = dict(job.raw_data or {})
    return str(raw.get("selected_apply_url") or job.url or "").strip()


def _record_block(
    db,
    application: Application,
    user: User,
    job: Job,
    *,
    platform: str,
    approval_reference: Optional[str],
    reason: str,
) -> None:
    payload = {
        "approval_reference": approval_reference,
        "platform": platform,
        "reason": reason[:500],
    }
    recent = (
        db.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.event_type == "supervised_submission_blocked",
        )
        .order_by(ApplicationEvent.id.desc())
        .limit(10)
        .all()
    )
    duplicate = any(
        (item.payload or {}).get("approval_reference") == approval_reference
        and (item.payload or {}).get("platform") == platform
        and (item.payload or {}).get("reason") == payload["reason"]
        for item in recent
    )
    if duplicate:
        return
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="supervised_submission_blocked",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload=payload,
        )
    )
    db.add(
        Notification(
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
        )
    )


def install_supervised_submission_task_gate() -> None:
    """Require an exact one-time approval for every live worker run.

    Dry runs retain their existing behavior. A live run must target a platform in
    the supervised registry and carry an active exact-payload approval. Approval is
    consumed before the original worker starts, so a crash cannot silently replay a
    previously approved final action.
    """

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
    ):
        if dry_run:
            return _ORIGINAL_RUN(application_id, dry_run=True)

        db = application_tasks.SessionLocal()
        try:
            application = (
                db.query(Application)
                .filter(Application.id == application_id)
                .with_for_update()
                .first()
            )
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
                return {
                    "success": False,
                    "dry_run": False,
                    "application_id": application.id,
                    "requires_manual_review": False,
                    "approval_required": False,
                    "supervised_platform_supported": False,
                    "platform": platform,
                    "error": reason,
                }

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
                return {
                    "success": False,
                    "dry_run": False,
                    "application_id": application.id,
                    "requires_manual_review": False,
                    "approval_required": True,
                    "supervised_platform_supported": True,
                    "platform": platform,
                    "error": reason,
                }

            try:
                approval = validate_supervised_approval(
                    db,
                    application,
                    user,
                    job,
                    reference=approval_reference,
                    consume=True,
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
                return {
                    "success": False,
                    "dry_run": False,
                    "application_id": application.id,
                    "requires_manual_review": False,
                    "approval_required": True,
                    "approval_reference": approval_reference,
                    "supervised_platform_supported": True,
                    "platform": platform,
                    "error": reason,
                }

            db.commit()
            consumed_reference = approval.reference
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        result = _ORIGINAL_RUN(application_id, dry_run=False)
        if isinstance(result, dict):
            result.setdefault("approval_reference", consumed_reference)
            result.setdefault("supervised_pilot", True)
            result.setdefault("supervised_platform", platform)
        return result

    task.run = wrapped_run
    _INSTALLED = True


__all__ = ["install_supervised_submission_task_gate"]
