"""Execute the already-prepared Lever final action once.

This module deliberately does not create, navigate, reconnect, or replace browser
sessions. It assumes the existing operator-assisted preparation flow has already
retained the exact Lever final-submit handoff and reuses the current once-only
operator_submit safety path.
"""

from __future__ import annotations

from typing import Any

from app.database import SessionLocal
from app.models.application import Application
from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.services import browser_handoff as browser_handoff_service
from app.services.operator_assisted_final_action import (
    claim_operator_final_action,
    finalize_operator_final_action,
)
from app.services.operator_assisted_submission import (
    OperatorAssistedSubmissionError,
    build_operator_assisted_preflight,
    issue_operator_assisted_approval,
    validate_operator_assisted_approval,
)
from app.services.supervised_target_identity import (
    persist_supervised_target_metadata,
    resolve_supervised_target_metadata,
)


def _load(db, application_id: int, handoff_public_id: str):
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise OperatorAssistedSubmissionError("Application not found")
    user = db.query(User).filter(User.id == application.user_id).first()
    job = db.query(Job).filter(Job.id == application.job_id).first()
    session = db.query(ManualHandoffSession).filter(
        ManualHandoffSession.public_id == handoff_public_id,
        ManualHandoffSession.application_id == application.id,
        ManualHandoffSession.user_id == application.user_id,
        ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
    ).first()
    if user is None or job is None:
        raise OperatorAssistedSubmissionError("Application user or job is missing")
    if session is None:
        raise OperatorAssistedSubmissionError("Retained final-submit handoff not found")
    return application, user, job, session


def _blocked(handoff_public_id: str, reason: str) -> dict[str, Any]:
    return {
        "success": False,
        "requires_manual_review": True,
        "handoff_public_id": handoff_public_id,
        "error": reason,
        "final_submit_clicked_by_jobtomatik": False,
        "automatic_retry_allowed": False,
    }


async def submit_retained_lever_final_action(
    application_id: int,
    handoff_public_id: str,
) -> dict[str, Any]:
    """Click the retained Lever Submit control once and return its confirmation result."""

    db = SessionLocal()
    approval_reference = ""
    try:
        application, user, job, session = _load(db, application_id, handoff_public_id)
        target_metadata = await resolve_supervised_target_metadata(job)
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
            return _blocked(
                handoff_public_id,
                "Final submit preflight blocked: " + ", ".join(preflight["blockers"]),
            )

        approval = issue_operator_assisted_approval(
            db,
            application,
            user,
            job,
            handoff_public_id=handoff_public_id,
            confirm_employer=preflight["employer"],
            confirm_role=preflight["role"],
            confirm_application_url=preflight["application_url"],
            confirm_operator_final_click=True,
            expires_in_minutes=5,
            notes="Authorized by the authenticated operator-assisted application request.",
            target_metadata=target_metadata,
        )
        validate_operator_assisted_approval(
            db,
            application,
            user,
            job,
            reference=approval.reference,
            consume=True,
            target_metadata=target_metadata,
        )
        approval = claim_operator_final_action(
            db,
            application,
            session,
            user_id=application.user_id,
        )
        approval_reference = approval.reference
        db.commit()
    except Exception as exc:
        db.rollback()
        return _blocked(handoff_public_id, str(exc))
    finally:
        db.close()

    try:
        result = await browser_handoff_service.perform_handoff_action(
            session,
            action="operator_submit",
        )
    except Exception as exc:
        db = SessionLocal()
        try:
            application = db.query(Application).filter(Application.id == application_id).first()
            persisted_session = db.query(ManualHandoffSession).filter(
                ManualHandoffSession.public_id == handoff_public_id
            ).first()
            approval = db.query(SubmissionApproval).filter(
                SubmissionApproval.reference == approval_reference
            ).first()
            if application and persisted_session and approval:
                finalize_operator_final_action(
                    db,
                    application,
                    persisted_session,
                    approval,
                    error=exc,
                )
                db.commit()
        finally:
            db.close()
        return _blocked(
            handoff_public_id,
            "Final submit outcome is uncertain; automatic retry is disabled.",
        )

    result = dict(result or {})
    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        persisted_session = db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == handoff_public_id
        ).first()
        approval = db.query(SubmissionApproval).filter(
            SubmissionApproval.reference == approval_reference
        ).first()
        if not application or not persisted_session or not approval:
            raise OperatorAssistedSubmissionError("Final-submit records disappeared during reconciliation")

        persisted_session.current_url = str(
            result.get("current_url") or persisted_session.current_url or ""
        )
        persisted_session.current_fingerprint = str(
            result.get("current_fingerprint") or persisted_session.current_fingerprint or ""
        )
        finalize_operator_final_action(
            db,
            application,
            persisted_session,
            approval,
            result=result,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        return _blocked(handoff_public_id, str(exc))
    finally:
        db.close()

    return {
        **result,
        "approval_reference": approval_reference,
        "handoff_public_id": handoff_public_id,
        "final_submit_clicked_by_jobtomatik": True,
        "automatic_retry_allowed": False,
    }


__all__ = ["submit_retained_lever_final_action"]
