import asyncio
import logging
from datetime import datetime
from typing import Any, Coroutine, Dict

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewTask,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services.application_state import (
    create_manual_review_task,
    has_sufficient_submission_evidence,
    resolve_manual_review_task,
    transition_application_state,
)
from app.services.browser_handoff import (
    BrowserHandoffUnavailable,
    resume_handoff_application,
    terminate_retained_browser,
)
from app.services.handoff_integration import install_handoff_task_integration
from app.services.handoff_session import (
    HandoffSessionConflict,
    begin_handoff_resume,
    complete_handoff_resume,
    fail_handoff_resume,
)
from app.tasks.applications import _profile_dict, _record_result_evidence

logger = logging.getLogger(__name__)
settings = get_settings()

# This module is part of Celery's explicit include list. Installing here makes
# retained handoff attachment deterministic even when worker lifecycle signals
# are not emitted by the local Android/PRoot pool implementation.
install_handoff_task_integration()


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


@celery_app.task(bind=True, name="app.tasks.handoffs.resume_handoff_session_task", queue="applications")
def resume_handoff_session_task(self, handoff_public_id: str):
    db = SessionLocal()
    session = None
    try:
        session = (
            db.query(ManualHandoffSession)
            .filter(ManualHandoffSession.public_id == handoff_public_id)
            .with_for_update()
            .first()
        )
        if not session:
            return {"error": "Handoff session not found"}
        if session.status == HandoffSessionStatus.completed.value:
            return {
                "success": True,
                "idempotent": True,
                "handoff_public_id": session.public_id,
                "status": session.status,
            }

        app = db.query(Application).filter(Application.id == session.application_id).first()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == session.manual_review_id).first()
        if not app or not review:
            fail_handoff_resume(db, session, reason="Application or review record is missing.", retryable=False)
            db.commit()
            return {"error": session.failure_reason}
        user = db.query(User).filter(User.id == app.user_id).first()
        job = db.query(Job).filter(Job.id == app.job_id).first()
        if not user or not job:
            fail_handoff_resume(db, session, reason="User or job record is missing.", retryable=False)
            db.commit()
            return {"error": session.failure_reason}

        dry_run = bool((session.handoff_metadata or {}).get("dry_run", True))
        if not dry_run and not settings.allow_real_application_submit:
            fail_handoff_resume(
                db,
                session,
                reason="Live submission remains disabled by the global safety gate.",
                retryable=False,
            )
            db.commit()
            return {"error": session.failure_reason, "requires_manual_review": True}

        begin_handoff_resume(db, session)
        transition_application_state(
            db,
            app,
            ApplicationAutomationState.applying,
            "handoff_resume_application_started",
            {"handoff_public_id": session.public_id, "dry_run": dry_run},
        )
        app.status = ApplicationStatus.applying
        db.commit()

        result: Dict[str, Any] = _run_async(
            resume_handoff_application(
                session,
                user_profile=_profile_dict(user, db, job),
                cover_letter=app.cover_letter or "",
                resume_path=user.resume_path or "",
                dry_run=dry_run,
            )
        )
        app.automation_log = list(app.automation_log or []) + list(result.get("log") or [])
        session.current_url = result.get("url") or session.current_url
        _record_result_evidence(db, app, result)
        db.flush()

        # A user can complete an employer submission while JobTomatik is operating in
        # dry-run mode. Explicit employer confirmation is authoritative and must win
        # over the original dry-run flag so the application is not offered again.
        if (
            result.get("success")
            and result.get("submission_confirmed")
            and has_sufficient_submission_evidence(db, app.id)
        ):
            app.status = ApplicationStatus.applied
            app.applied_at = app.applied_at or datetime.utcnow()
            resolve_manual_review_task(
                db,
                app,
                review,
                "Employer confirmation page detected after the human challenge.",
            )
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.submitted,
                "handoff_submission_confirmation_detected",
                {
                    "handoff_public_id": session.public_id,
                    "final_url": result.get("url"),
                    "dry_run_started": dry_run,
                },
            )
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.confirmed,
                "handoff_submission_confirmed",
                {
                    "handoff_public_id": session.public_id,
                    "evidence_count": len(result.get("confirmation_evidence") or []),
                },
            )
            complete_handoff_resume(
                db,
                session,
                result={
                    "submitted": True,
                    "confirmed": True,
                    "dry_run_started": dry_run,
                    "final_url": result.get("url"),
                },
            )
            terminate_retained_browser(session)
            db.commit()
            return result

        if result.get("success") and dry_run and result.get("ready_to_submit"):
            app.status = ApplicationStatus.pending
            resolve_manual_review_task(db, app, review, "Human challenge completed and browser flow resumed.")
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.ready_to_apply,
                "handoff_dry_run_completed",
                {
                    "handoff_public_id": session.public_id,
                    "fields_filled": result.get("fields_filled", 0),
                    "adapter": result.get("ats_adapter"),
                },
            )
            complete_handoff_resume(
                db,
                session,
                result={
                    "dry_run": True,
                    "ready_to_submit": True,
                    "adapter": result.get("ats_adapter"),
                },
            )
            terminate_retained_browser(session)
            db.commit()
            return result

        if result.get("success") and not dry_run and has_sufficient_submission_evidence(db, app.id):
            app.status = ApplicationStatus.applied
            app.applied_at = datetime.utcnow()
            resolve_manual_review_task(db, app, review, "Human challenge completed and submission confirmed.")
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.submitted,
                "handoff_submission_evidence_accepted",
                {"handoff_public_id": session.public_id},
            )
            complete_handoff_resume(db, session, result={"submitted": True})
            terminate_retained_browser(session)
            db.commit()
            return result

        app.status = ApplicationStatus.pending
        reason = result.get("error") or "The retained browser could not continue safely."
        retryable = bool(result.get("requires_manual_review")) and session.resume_attempt_count < session.max_resume_attempts
        fail_handoff_resume(db, session, reason=reason, retryable=retryable)
        target_state = (
            ApplicationAutomationState.needs_review
            if retryable
            else ApplicationAutomationState.failed
        )
        transition_application_state(
            db,
            app,
            target_state,
            "handoff_resume_requires_review" if retryable else "handoff_resume_failed",
            {"handoff_public_id": session.public_id, "error": reason[:500]},
        )
        if not retryable:
            create_manual_review_task(
                db,
                app,
                ManualReviewReason.automation_error,
                reason,
                details={"handoff_public_id": session.public_id, "result": result},
                blocking_url=session.current_url,
                target_state=target_state,
            )
        db.commit()
        return result
    except (BrowserHandoffUnavailable, HandoffSessionConflict) as exc:
        db.rollback()
        if session:
            session = db.query(ManualHandoffSession).filter(
                ManualHandoffSession.id == session.id
            ).first()
            if session:
                try:
                    fail_handoff_resume(db, session, reason=str(exc), retryable=False)
                    db.commit()
                except Exception:
                    db.rollback()
        return {"error": str(exc), "requires_manual_review": True}
    except Exception as exc:
        logger.exception("resume_handoff_session_task failed")
        db.rollback()
        raise self.retry(exc=exc, countdown=30, max_retries=2)
    finally:
        db.close()
