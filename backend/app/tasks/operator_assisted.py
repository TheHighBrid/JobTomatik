"""Prepare a filled retained ATS page, then finish a verified Lever final action."""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.services.operator_assisted_handoff_integration import (
    install_operator_assisted_handoff_integration,
    operator_prepare_scope,
)
from app.services.operator_assisted_question_retention import (
    install_operator_assisted_question_retention,
    summarize_operator_question_retention_result,
)
from app.services.operator_assisted_submission import (
    OperatorAssistedSubmissionError,
    build_operator_assisted_preflight,
)
from app.services.supervised_target_identity import (
    persist_supervised_target_metadata,
    resolve_supervised_target_metadata,
)
from app.tasks.applications import submit_application_task


install_operator_assisted_handoff_integration()
install_operator_assisted_question_retention()


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _final_submit_handoff_id(result: dict[str, Any]) -> str:
    """Return the retained handoff only for the exact final-submit review boundary."""

    from app.models.application import ManualReviewReason

    final_reason = ManualReviewReason.operator_final_submit_required.value
    if not any(
        isinstance(item, dict) and str(item.get("reason_code") or "") == final_reason
        for item in result.get("review_items") or []
    ):
        return ""
    return str(result.get("handoff_public_id") or "")


def _reconcile_confirmed_submission(
    application_id: int,
    handoff_public_id: str,
    result: dict[str, Any],
) -> bool:
    """Persist proof and close a confirmed Lever submission."""

    from datetime import datetime

    from app.models.application import (
        ApplicationAutomationState,
        ApplicationStatus,
        ManualReviewTask,
    )
    from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
    from app.services.application_state import (
        has_sufficient_submission_evidence,
        normalize_state,
        resolve_manual_review_task,
        transition_application_state,
    )
    from app.tasks.applications import _record_result_evidence

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        session = db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == handoff_public_id,
            ManualHandoffSession.application_id == application_id,
        ).first()
        if application is None or session is None:
            return False

        evidence_result = {
            **result,
            "url": str(result.get("current_url") or session.current_url or ""),
        }
        _record_result_evidence(db, application, evidence_result)
        db.flush()
        if not has_sufficient_submission_evidence(db, application.id):
            db.rollback()
            return False

        review = db.query(ManualReviewTask).filter(
            ManualReviewTask.id == session.manual_review_id
        ).first()
        if review is not None:
            resolve_manual_review_task(
                db,
                application,
                review,
                "Lever employer confirmation detected after JobTomatik final submit.",
            )

        application.status = ApplicationStatus.applied
        application.applied_at = application.applied_at or datetime.utcnow()
        if normalize_state(application.automation_state) in {
            ApplicationAutomationState.needs_review.value,
            ApplicationAutomationState.ready_to_apply.value,
        }:
            transition_application_state(
                db,
                application,
                ApplicationAutomationState.applying,
                "operator_assisted_submission_reconciliation_started",
                {"handoff_public_id": session.public_id},
            )
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.submitted,
            "operator_assisted_submission_confirmation_detected",
            {
                "handoff_public_id": session.public_id,
                "final_url": evidence_result["url"],
                "confirmation_detector": result.get("confirmation_detector"),
                "approval_reference": result.get("approval_reference"),
                "confirmed_at": datetime.utcnow().isoformat(),
            },
        )
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.confirmed,
            "operator_assisted_submission_confirmed",
            {
                "handoff_public_id": session.public_id,
                "evidence_count": len(result.get("confirmation_evidence") or []),
            },
        )
        session.status = HandoffSessionStatus.completed.value
        session.completed_at = session.completed_at or datetime.utcnow()
        session.failure_reason = None
        session.lock_version = (session.lock_version or 0) + 1

        note = (
            f"[{datetime.utcnow().isoformat()}] Lever submission confirmed by JobTomatik; "
            f"final URL: {evidence_result['url']}."
        )
        application.notes = (
            f"{application.notes.rstrip()}\n{note}" if application.notes else note
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()


def _record_unconfirmed_final_submit(
    application_id: int,
    handoff_public_id: str,
    result: dict[str, Any],
) -> str:
    """Move an unconfirmed final action into an explicit no-retry state."""

    from datetime import datetime

    from app.models.application import (
        ApplicationAutomationState,
        ApplicationEvent,
        ApplicationStatus,
        ManualReviewReason,
        ManualReviewTask,
    )
    from app.models.handoff import ManualHandoffSession
    from app.services.application_state import (
        create_manual_review_task,
        normalize_state,
    )

    details = {
        "handoff_public_id": handoff_public_id,
        "approval_reference": result.get("approval_reference"),
        "final_submit_click_possible": bool(result.get("final_submit_click_possible")),
        "submission_confirmed": False,
        "observed_at": datetime.utcnow().isoformat(),
        "final_url": result.get("current_url"),
        "final_fingerprint": result.get("current_fingerprint"),
        "pre_submit_url": result.get("pre_submit_url"),
        "confirmation_detector": result.get("confirmation_detector"),
        "confirmation_evidence": [
            item
            for item in result.get("confirmation_evidence") or []
            if isinstance(item, dict)
        ][:5],
        "passive_confirmation": dict(result.get("passive_confirmation") or {}),
        "idempotency_guard": result.get("idempotency_guard"),
        "error": str(result.get("action_error") or result.get("error") or "")[:500]
        or None,
        "automatic_retry_allowed": False,
    }

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        if application is None:
            return ""
        state = normalize_state(application.automation_state)
        if state != ApplicationAutomationState.applying.value:
            db.add(
                ApplicationEvent(
                    application_id=application.id,
                    event_type="operator_assisted_auto_final_submit_not_started",
                    from_state=state,
                    to_state=state,
                    payload=details,
                )
            )
            db.commit()
            return state

        session = db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == handoff_public_id,
            ManualHandoffSession.application_id == application_id,
        ).first()
        blocking_url = str(
            details.get("final_url") or getattr(session, "current_url", "") or ""
        ) or None

        if details["final_submit_click_possible"]:
            create_manual_review_task(
                db,
                application,
                ManualReviewReason.submission_confirmation_uncertain,
                "JobTomatik clicked the retained Lever Submit control but no employer "
                "confirmation was observed. Verify the employer page or email before any "
                "retry; automatic resubmission is disabled.",
                details=details,
                blocking_url=blocking_url,
                target_state=ApplicationAutomationState.submission_uncertain,
            )
            note_outcome = "submit clicked, confirmation not observed"
        else:
            review = None
            if session is not None and session.manual_review_id:
                review = db.query(ManualReviewTask).filter(
                    ManualReviewTask.id == session.manual_review_id
                ).first()
            create_manual_review_task(
                db,
                application,
                ManualReviewReason.operator_final_submit_required,
                "JobTomatik did not click the retained Lever Submit control because a "
                "final-action safety check failed. The filled page is still retained.",
                details={
                    **dict(getattr(review, "details", None) or {}),
                    "automatic_final_submit": details,
                },
                blocking_url=blocking_url,
                target_state=ApplicationAutomationState.needs_review,
            )
            note_outcome = "submit not clicked (safety check failed)"

        application.status = ApplicationStatus.pending
        note = (
            f"[{details['observed_at']}] Automatic Lever final submit: {note_outcome}; "
            f"final URL: {details.get('final_url') or 'unknown'}."
        )
        application.notes = (
            f"{application.notes.rstrip()}\n{note}" if application.notes else note
        )
        db.commit()
        return normalize_state(application.automation_state)
    except Exception:
        db.rollback()
        return ""
    finally:
        db.close()


def _finish_retained_lever_boundary(
    application_id: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Lazy-load final-submit code only after the known-good fill path has finished."""

    handoff_public_id = _final_submit_handoff_id(result)
    if not handoff_public_id:
        return result

    # Keep the restored #582 Chrome/tab-opening path isolated from the final-click
    # implementation. Importing this executor is deliberately delayed until the exact
    # retained final-submit boundary already exists.
    from app.models.application import ApplicationAutomationState, ApplicationStatus
    from app.services.operator_assisted_auto_submit import (
        submit_retained_lever_final_action,
    )

    final_result = _run_async(
        submit_retained_lever_final_action(application_id, handoff_public_id)
    )
    merged = {**result, **dict(final_result or {})}
    merged["operator_assisted"] = True
    merged["automatic_retry_allowed"] = False

    if not bool(merged.get("submission_confirmed")):
        merged["success"] = False
        merged["requires_manual_review"] = True
        merged["automation_state"] = _record_unconfirmed_final_submit(
            application_id,
            handoff_public_id,
            merged,
        )
        return merged

    if not _reconcile_confirmed_submission(application_id, handoff_public_id, merged):
        failed = {
            **merged,
            "success": False,
            "requires_manual_review": True,
            "submission_confirmed": False,
            "final_submit_click_possible": True,
            "error": "Submission confirmation was observed but could not be reconciled safely.",
        }
        failed["automation_state"] = _record_unconfirmed_final_submit(
            application_id,
            handoff_public_id,
            failed,
        )
        return failed

    return {
        **merged,
        "success": True,
        "requires_manual_review": False,
        "application_status": ApplicationStatus.applied.value,
        "automation_state": ApplicationAutomationState.confirmed.value,
    }


@celery_app.task(
    bind=True,
    name="app.tasks.operator_assisted.prepare_operator_assisted_application_task",
    queue="applications",
)
def prepare_operator_assisted_application_task(self, application_id: int):
    """Fill first; submit only after the exact retained final boundary is proven."""

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            return {"error": "Application not found", "success": False}
        user = db.query(User).filter(User.id == application.user_id).first()
        job = db.query(Job).filter(Job.id == application.job_id).first()
        if not user or not job:
            return {"error": "Application user or job is missing", "success": False}

        target_metadata = _run_async(resolve_supervised_target_metadata(job))
        if target_metadata:
            persist_supervised_target_metadata(job, target_metadata)
        preflight = build_operator_assisted_preflight(
            db,
            application,
            user,
            job,
            target_metadata=target_metadata,
        )
        if not preflight["ready"]:
            return {
                "success": False,
                "requires_manual_review": False,
                "operator_assisted": True,
                "error": "Operator-assisted preparation is blocked: "
                + ", ".join(preflight["blockers"]),
                "blockers": list(preflight["blockers"]),
            }
        db.commit()
    except OperatorAssistedSubmissionError as exc:
        db.rollback()
        return {
            "success": False,
            "operator_assisted": True,
            "error": str(exc),
        }
    finally:
        db.close()

    try:
        with operator_prepare_scope(target_metadata or {}):
            result = submit_application_task.run(application_id, dry_run=True)
        if isinstance(result, dict):
            result = summarize_operator_question_retention_result(dict(result))
            result["operator_assisted"] = True
            result["automated_submission_authorized"] = False
            result["final_submit_clicked_by_jobtomatik"] = False
        else:
            return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30, max_retries=1)

    return _finish_retained_lever_boundary(application_id, result)


__all__ = ["prepare_operator_assisted_application_task"]
