"""Complete an explicitly requested Lever application after its page is retained.

Imported after preparation, never during worker/browser bootstrap. The existing
operator-submit boundary owns the one click and all live target/security checks.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.database import SessionLocal
from app.models.application import (
    Application, ApplicationAutomationState, ApplicationStatus, ManualReviewReason,
    ManualReviewStatus, ManualReviewTask,
)
from app.models.handoff import HandoffChallengeType, HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.services import browser_handoff
from app.services.application_integrity import submission_is_closed
from app.services.application_state import (
    create_manual_review_task, has_sufficient_submission_evidence, normalize_state,
    resolve_manual_review_task, transition_application_state,
)
from app.services.operator_assisted_final_action import (
    claim_operator_final_action, finalize_operator_final_action,
)
from app.services.operator_assisted_submission import (
    OperatorAssistedSubmissionError, build_operator_assisted_preflight,
    issue_operator_assisted_approval, operator_completion_binding,
    validate_operator_assisted_approval,
)
from app.services.supervised_target_identity import resolve_supervised_target_metadata

logger = logging.getLogger(__name__)
CONFIRMATION_RECHECK_ATTEMPTS = 4
CONFIRMATION_RECHECK_INTERVAL_SECONDS = 2.5
FINAL_REASON = ManualReviewReason.operator_final_submit_required.value


def _load_handoff(db, application_id, public_id):
    return db.query(ManualHandoffSession).filter(
        ManualHandoffSession.application_id == application_id,
        ManualHandoffSession.public_id == public_id,
        ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
    ).first()


def _guard(db, application, session):
    if application is None or session is None or session.user_id != application.user_id:
        raise OperatorAssistedSubmissionError("The exact retained application was not found.")
    if submission_is_closed(application):
        raise OperatorAssistedSubmissionError("The application is already submitted or closed.")
    if normalize_state(application.automation_state) == ApplicationAutomationState.submission_uncertain.value:
        raise OperatorAssistedSubmissionError("The previous submission outcome is uncertain; automatic retry is forbidden.")
    if session.status != HandoffSessionStatus.awaiting_user.value:
        raise OperatorAssistedSubmissionError("The retained page is already claimed or no longer available.")
    approvals = db.query(SubmissionApproval).filter(
        SubmissionApproval.application_id == application.id,
    ).all()
    if any((approval.approval_metadata or {}).get("operator_submit_action_started_at") for approval in approvals):
        raise OperatorAssistedSubmissionError("A final submit action was already started; verify its outcome instead of retrying.")
    other_review = db.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
        ManualReviewTask.status.in_([ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]),
        ManualReviewTask.reason_code != FINAL_REASON,
    ).first()
    if other_review is not None:
        raise OperatorAssistedSubmissionError("An unanswered question or another review still blocks submission.")


async def _claim(application_id, public_id, binding):
    db = SessionLocal()
    try:
        # Serialize competing requests before issuing or consuming an approval.
        application = db.query(Application).filter(Application.id == application_id).with_for_update().first()
        session = _load_handoff(db, application_id, public_id)
        _guard(db, application, session)
        user = db.query(User).filter(User.id == application.user_id).one()
        job = db.query(Job).filter(Job.id == application.job_id).one()
        target = await resolve_supervised_target_metadata(job)
        preflight = build_operator_assisted_preflight(db, application, user, job, target_metadata=target)
        if not preflight["ready"]:
            raise OperatorAssistedSubmissionError("Final submit is blocked: " + ", ".join(preflight["blockers"]))
        if (preflight["platform"] != "lever" or not all(binding.values())
                or binding != operator_completion_binding(preflight)):
            raise OperatorAssistedSubmissionError("The requested application payload or target changed. Review it before submitting.")
        approval = issue_operator_assisted_approval(
            db, application, user, job, handoff_public_id=public_id,
            confirm_employer=preflight["employer"], confirm_role=preflight["role"],
            confirm_application_url=preflight["application_url"], confirm_operator_final_click=True,
            expires_in_minutes=5, target_metadata=target,
            notes="Explicit authenticated Fill and submit request for the bound application.",
        )
        approval.approval_metadata = {**dict(approval.approval_metadata or {}), "completion_request": dict(binding)}
        validate_operator_assisted_approval(
            db, application, user, job, reference=approval.reference, consume=True, target_metadata=target,
        )
        # Production sessions disable autoflush and expire instances on commit.
        db.flush()
        claim_operator_final_action(db, application, session, user_id=user.id)
        reference = approval.reference
        db.commit()
        db.refresh(session)
        db.expunge(session)
        return session, reference
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _fresh_handoff(application_id, public_id):
    db = SessionLocal()
    try:
        return _load_handoff(db, application_id, public_id)
    finally:
        db.close()


async def _observe_confirmation(session, result):
    """Wait for a slow confirmation redirect with read-only checks, never a retry."""
    for attempt in range(CONFIRMATION_RECHECK_ATTEMPTS):
        if attempt:
            await asyncio.sleep(CONFIRMATION_RECHECK_INTERVAL_SECONDS)
        try:
            verification = await browser_handoff.verify_browser_handoff_completion(session)
            evidence = dict(verification.evidence or {})
            result.update(current_url=verification.current_url, current_fingerprint=verification.current_fingerprint)
            if verification.challenge_cleared and evidence.get("submission_confirmed"):
                result.update(
                    submission_confirmed=True,
                    confirmation_evidence=list(evidence.get("confirmation_evidence") or []),
                    confirmation_detector="retained_operator_completion_verifier",
                    target_verification=dict(evidence.get("target_verification") or {}),
                )
                return
        except Exception as exc:
            logger.info("Retained confirmation check %s failed: %s", attempt + 1, type(exc).__name__)


def _record_outcome(application_id, public_id, reference, result):
    # Keep application-task imports out of the worker's preparation/bootstrap path.
    from app.tasks.applications import _record_result_evidence

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).with_for_update().one()
        session = _load_handoff(db, application_id, public_id)
        approval = db.query(SubmissionApproval).filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.reference == reference,
        ).one()
        if session is None:
            raise OperatorAssistedSubmissionError("The retained handoff disappeared during reconciliation.")
        if submission_is_closed(application):
            # A read-only handoff verifier may already have reconciled the same page.
            return
        session.current_url = str(result.get("current_url") or session.current_url or "")
        session.current_fingerprint = str(result.get("current_fingerprint") or session.current_fingerprint or "")
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == session.manual_review_id).first()
        if result.get("submission_confirmed"):
            _record_result_evidence(db, application, {**result, "url": session.current_url})
            db.flush()
            if not has_sufficient_submission_evidence(db, application.id):
                result.update(submission_confirmed=False, error="Employer confirmation could not be recorded as sufficient evidence.")
        finalize_operator_final_action(db, application, session, approval, result=result)
        now = datetime.utcnow()
        if result.get("submission_confirmed"):
            if review is not None:
                resolve_manual_review_task(db, application, review, "Lever confirmed the requested JobTomatik submission.")
            application.status = ApplicationStatus.applied
            application.applied_at = application.applied_at or now
            transition_application_state(db, application, ApplicationAutomationState.submitted,
                "operator_assisted_submission_confirmation_detected", {"handoff_public_id": public_id, "final_url": session.current_url})
            transition_application_state(db, application, ApplicationAutomationState.confirmed,
                "operator_assisted_submission_confirmed", {"approval_reference": reference})
            session.status = HandoffSessionStatus.completed.value
            session.completed_at = session.completed_at or now
            session.failure_reason = None
            session.lock_version = (session.lock_version or 0) + 1
            note = "Lever submission confirmed; final URL: " + session.current_url
            result.update(success=True, requires_manual_review=False, error=None, review_items=[],
                application_status=ApplicationStatus.applied.value, automation_state=ApplicationAutomationState.confirmed.value)
        else:
            uncertain = result["final_submit_click_possible"]
            reason = ManualReviewReason.submission_confirmation_uncertain if uncertain else ManualReviewReason.operator_final_submit_required
            state = ApplicationAutomationState.submission_uncertain if uncertain else ApplicationAutomationState.needs_review
            note = result.get("error") or "Submit was clicked, but employer confirmation has not been observed. Verify the retained page before retrying."
            create_manual_review_task(db, application, reason, note,
                details={**dict(getattr(review, "details", None) or {}), "completion_outcome": dict(result)},
                blocking_url=session.current_url, target_state=state)
            application.status = ApplicationStatus.pending
            result.update(success=False, requires_manual_review=True, error=note,
                automation_state=state.value)
        note = f"[{now.isoformat()}] {note}"
        application.notes = f"{application.notes.rstrip()}\n{note}" if application.notes else note
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def complete_retained_lever_application(application_id: int, public_id: str, binding: dict[str, Any]) -> dict[str, Any]:
    """Authorize, click once, observe and reconcile the exact retained application."""
    result = {
        "success": False, "requires_manual_review": True, "handoff_public_id": public_id,
        "submission_confirmed": False, "final_submit_clicked_by_jobtomatik": False,
        "final_submit_click_possible": False, "automatic_retry_allowed": False,
    }
    try:
        session, reference = await _claim(application_id, public_id, binding)
    except Exception as exc:
        return {**result, "error": str(exc)}
    result["approval_reference"] = reference
    try:
        action = await browser_handoff.perform_handoff_action(session, action="operator_submit")
        result.update(action, final_submit_clicked_by_jobtomatik=True, final_submit_click_possible=True)
    except Exception as exc:
        result["error"] = str(exc)
        session = _fresh_handoff(application_id, public_id)
        metadata = dict(getattr(session, "handoff_metadata", None) or {})
        result["final_submit_click_possible"] = session is None or bool(metadata.get("operator_submit_live_snapshot_checkpointed"))
        if result["final_submit_click_possible"]:
            result["final_submit_clicked_by_jobtomatik"] = None  # The checkpoint alone cannot prove a click.
    if result["final_submit_click_possible"] and not result.get("submission_confirmed") and session is not None:
        await _observe_confirmation(session, result)
    _record_outcome(application_id, public_id, reference, result)
    return result
