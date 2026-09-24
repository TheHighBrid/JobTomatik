"""Reconcile human final-submit actions observed in retained native Chrome."""
from __future__ import annotations

import asyncio
from datetime import datetime

from app.models.application import (
    Application, ApplicationAutomationState, ApplicationStatus,
    ManualReviewStatus, ManualReviewTask, SubmissionEvidence,
)
from app.models.handoff import HandoffChallengeType, HandoffSessionStatus, ManualHandoffSession
from app.services.application_state import (
    has_sufficient_submission_evidence, normalize_state, record_submission_evidence,
    resolve_manual_review_task, transition_application_state,
)
from app.services.browser_handoff import BrowserHandoffUnavailable, verify_browser_handoff_completion

ACTIVE = (HandoffSessionStatus.awaiting_user.value, HandoffSessionStatus.claimed.value, HandoffSessionStatus.ready.value)


def _verify(session):
    return asyncio.run(verify_browser_handoff_completion(session))


def _persist_evidence(db, app, verification):
    created = 0
    for item in (verification.evidence or {}).get("confirmation_evidence") or []:
        if not item.get("is_sufficient"):
            continue
        final_url = item.get("final_url") or verification.current_url
        text = item.get("confirmation_text")
        exists = db.query(SubmissionEvidence).filter(
            SubmissionEvidence.application_id == app.id,
            SubmissionEvidence.final_url == final_url,
            SubmissionEvidence.confirmation_text == text,
            SubmissionEvidence.is_sufficient.is_(True),
        ).first()
        if exists:
            continue
        record_submission_evidence(
            db, app, item.get("evidence_type") or "confirmation_page",
            is_sufficient=True, final_url=final_url, confirmation_text=text,
            selector=item.get("selector"), metadata=item.get("metadata") or {},
        )
        created += 1
    db.flush()
    return created


def _finish(db, app, session, verification):
    reviews = db.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == app.id,
        ManualReviewTask.status.in_([ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]),
    ).all()
    for review in reviews:
        resolve_manual_review_task(db, app, review, "Employer confirmation detected after human final submit.")

    state = normalize_state(app.automation_state)
    if state in {ApplicationAutomationState.preparing.value, ApplicationAutomationState.ready_to_apply.value, ApplicationAutomationState.needs_review.value, ApplicationAutomationState.failed.value}:
        transition_application_state(db, app, ApplicationAutomationState.applying, "operator_submission_reconciliation_started", {"handoff_public_id": session.public_id})
        state = ApplicationAutomationState.applying.value
    if state == ApplicationAutomationState.applying.value:
        transition_application_state(db, app, ApplicationAutomationState.submitted, "operator_submission_confirmation_detected", {"handoff_public_id": session.public_id, "final_url": verification.current_url})
        state = ApplicationAutomationState.submitted.value
    if state in {ApplicationAutomationState.submitted.value, ApplicationAutomationState.submission_uncertain.value}:
        transition_application_state(db, app, ApplicationAutomationState.confirmed, "operator_submission_confirmed", {"handoff_public_id": session.public_id, "final_url": verification.current_url})

    app.status = ApplicationStatus.applied
    app.applied_at = app.applied_at or datetime.utcnow()
    session.current_url = verification.current_url
    session.current_fingerprint = verification.current_fingerprint
    session.status = HandoffSessionStatus.completed.value
    session.completed_at = session.completed_at or datetime.utcnow()


def reconcile_operator_submissions(db):
    sessions = db.query(ManualHandoffSession).filter(
        ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
        ManualHandoffSession.status.in_(ACTIVE),
    ).order_by(ManualHandoffSession.created_at.asc()).all()
    results = []
    for session in sessions:
        app = db.query(Application).filter(Application.id == session.application_id).first()
        if app is None or app.status == ApplicationStatus.applied:
            continue
        try:
            verification = _verify(session)
        except BrowserHandoffUnavailable as exc:
            results.append({"application_id": session.application_id, "confirmed": False, "reason": str(exc)})
            continue
        except Exception as exc:
            results.append({"application_id": session.application_id, "confirmed": False, "reason": type(exc).__name__})
            continue
        if not (verification.evidence or {}).get("submission_confirmed"):
            results.append({"application_id": app.id, "confirmed": False, "reason": "confirmation_not_observed"})
            continue
        created = _persist_evidence(db, app, verification)
        if not has_sufficient_submission_evidence(db, app.id):
            results.append({"application_id": app.id, "confirmed": False, "reason": "sufficient_evidence_missing"})
            continue
        _finish(db, app, session, verification)
        results.append({"application_id": app.id, "confirmed": True, "final_url": verification.current_url, "evidence_created": created})
    return {"checked": len(sessions), "confirmed": sum(bool(x.get("confirmed")) for x in results), "results": results}
