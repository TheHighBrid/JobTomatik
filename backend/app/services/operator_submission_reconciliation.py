"""Reconcile human final-submit actions observed in the retained employer browser.

The operator may click the employer's final Submit control directly in native Chrome.
That action happens outside JobTomatik's HTTP request lifecycle, so this reconciler
turns strong employer confirmation into durable application state without requiring
a second bookkeeping click in the UI.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import HandoffChallengeType, HandoffSessionStatus, ManualHandoffSession
from app.services.application_state import (
    has_sufficient_submission_evidence,
    normalize_state,
    record_submission_evidence,
    resolve_manual_review_task,
    transition_application_state,
)
from app.services.browser_handoff import BrowserHandoffUnavailable, verify_browser_handoff_completion


_ACTIVE_HANDOFF_STATES = (
    HandoffSessionStatus.awaiting_user.value,
    HandoffSessionStatus.claimed.value,
    HandoffSessionStatus.ready.value,
)


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("operator submission reconciliation requires a synchronous worker context")


def _record_confirmation(db, application: Application, verification) -> int:
    evidence = list((verification.evidence or {}).get("confirmation_evidence") or [])
    created = 0
    for item in evidence:
        if not item.get("is_sufficient"):
            continue
        final_url = item.get("final_url") or verification.current_url
        confirmation_text = item.get("confirmation_text")
        duplicate = (
            db.query(type(application).submission_evidence.property.mapper.class_)
            .filter_by(
                application_id=application.id,
                final_url=final_url,
                confirmation_text=confirmation_text,
                is_sufficient=True,
            )
            .first()
        )
        if duplicate:
            continue
        record_submission_evidence(
            db,
            application,
            item.get("evidence_type") or "confirmation_page",
            is_sufficient=True,
            final_url=final_url,
            confirmation_text=confirmation_text,
            selector=item.get("selector"),
            metadata=item.get("metadata") or {},
        )
        created += 1
    db.flush()
    return created


def _finalize_application(db, application: Application, session: ManualHandoffSession, verification) -> None:
    open_reviews = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .all()
    )
    for review in open_reviews:
        resolve_manual_review_task(
            db,
            application,
            review,
            "Employer confirmation detected after the human final submit action.",
        )

    state = normalize_state(application.automation_state)
    if state in {
        ApplicationAutomationState.preparing.value,
        ApplicationAutomationState.ready_to_apply.value,
        ApplicationAutomationState.needs_review.value,
        ApplicationAutomationState.failed.value,
    }:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.applying,
            "operator_submission_reconciliation_started",
            {"handoff_public_id": session.public_id, "final_url": verification.current_url},
        )
        state = ApplicationAutomationState.applying.value

    if state == ApplicationAutomationState.applying.value:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.submitted,
            "operator_submission_confirmation_detected",
            {"handoff_public_id": session.public_id, "final_url": verification.current_url},
        )
        state = ApplicationAutomationState.submitted.value

    if state in {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.submission_uncertain.value,
    }:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.confirmed,
            "operator_submission_confirmed",
            {"handoff_public_id": session.public_id, "final_url": verification.current_url},
        )

    application.status = ApplicationStatus.applied
    application.applied_at = application.applied_at or datetime.utcnow()
    session.current_url = verification.current_url
    session.current_fingerprint = verification.current_fingerprint
    session.status = HandoffSessionStatus.completed.value
    session.completed_at = session.completed_at or datetime.utcnow()


def reconcile_operator_submissions(db) -> Dict[str, Any]:
    sessions = (
        db.query(ManualHandoffSession)
        .filter(
            ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
            ManualHandoffSession.status.in_(_ACTIVE_HANDOFF_STATES),
        )
        .order_by(ManualHandoffSession.created_at.asc())
        .all()
    )
    results = []
    for session in sessions:
        application = db.query(Application).filter(Application.id == session.application_id).first()
        if application is None or application.status == ApplicationStatus.applied:
            continue
        try:
            verification = _run(verify_browser_handoff_completion(session))
        except BrowserHandoffUnavailable as exc:
            results.append({"application_id": session.application_id, "confirmed": False, "reason": str(exc)})
            continue
        except Exception as exc:
            results.append({"application_id": session.application_id, "confirmed": False, "reason": type(exc).__name__})
            continue

        if not (verification.evidence or {}).get("submission_confirmed"):
            results.append({"application_id": application.id, "confirmed": False, "reason": "confirmation_not_observed"})
            continue

        evidence_created = _record_confirmation(db, application, verification)
        if not has_sufficient_submission_evidence(db, application.id):
            results.append({"application_id": application.id, "confirmed": False, "reason": "sufficient_evidence_missing"})
            continue
        _finalize_application(db, application, session, verification)
        results.append({
            "application_id": application.id,
            "confirmed": True,
            "final_url": verification.current_url,
            "evidence_created": evidence_created,
        })

    return {
        "checked": len(sessions),
        "confirmed": sum(1 for item in results if item.get("confirmed")),
        "results": results,
    }


__all__ = ["reconcile_operator_submissions"]
