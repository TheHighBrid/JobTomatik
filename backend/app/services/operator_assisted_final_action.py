"""Durable once-only checkpoint for the operator-assisted final submit action."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationEvent
from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.services.operator_assisted_submission import (
    OPERATOR_ASSISTED_APPROVAL_SOURCE,
    OperatorAssistedSubmissionError,
)


def _now() -> datetime:
    return datetime.utcnow()


def _bound_consumed_approval(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
    for_update: bool = False,
) -> Optional[SubmissionApproval]:
    query = db.query(SubmissionApproval).filter(
        SubmissionApproval.application_id == session.application_id,
        SubmissionApproval.user_id == user_id,
        SubmissionApproval.status == SubmissionApprovalStatus.consumed.value,
    )
    if for_update:
        query = query.with_for_update()
    approvals = query.order_by(
        SubmissionApproval.consumed_at.desc(),
        SubmissionApproval.id.desc(),
    ).all()
    for approval in approvals:
        metadata = dict(approval.approval_metadata or {})
        if (
            metadata.get("approval_source") == OPERATOR_ASSISTED_APPROVAL_SOURCE
            and metadata.get("handoff_public_id") == session.public_id
            and metadata.get("operator_final_click_required") is True
            and metadata.get("automated_submission_authorized") is False
            and metadata.get("queue_submission_authorized") is False
        ):
            return approval
    return None


def claim_operator_final_action(
    db: Session,
    application: Application,
    session: ManualHandoffSession,
    *,
    user_id: int,
) -> SubmissionApproval:
    """Persist a no-retry checkpoint before touching the employer Submit control."""

    if session.application_id != application.id or session.user_id != user_id:
        raise OperatorAssistedSubmissionError("Retained final-submit handoff ownership mismatch")
    if session.challenge_type != HandoffChallengeType.final_submit.value:
        raise OperatorAssistedSubmissionError("Handoff is not an operator final-submit boundary")

    approval = _bound_consumed_approval(
        db,
        session,
        user_id=user_id,
        for_update=True,
    )
    if approval is None:
        raise OperatorAssistedSubmissionError(
            "Consumed exact operator approval is required before final submit"
        )

    metadata = dict(approval.approval_metadata or {})
    if metadata.get("operator_submit_action_started_at"):
        raise OperatorAssistedSubmissionError(
            "The exact final submit action was already requested. Automatic retry is forbidden; "
            "verify the retained employer page instead."
        )

    now = _now()
    approval.approval_metadata = {
        **metadata,
        "operator_submit_action_started_at": now.isoformat(),
        "operator_submit_action_started": True,
        "operator_submit_action_completed": False,
        "operator_submit_action_result": "pending_external_action",
        "automatic_retry_allowed": False,
    }
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="operator_assisted_final_submit_action_started",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "approval_reference": approval.reference,
                "handoff_public_id": session.public_id,
                "automatic_retry_allowed": False,
            },
        )
    )
    db.flush()
    return approval


def finalize_operator_final_action(
    db: Session,
    application: Application,
    session: ManualHandoffSession,
    approval: SubmissionApproval,
    *,
    result: Optional[Mapping[str, Any]] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Record the external action outcome without ever reopening retry authority."""

    metadata = dict(approval.approval_metadata or {})
    now = _now()
    if error is not None:
        outcome = "uncertain"
        confirmed = False
        current_url = str(session.current_url or "")
        error_text = f"{type(error).__name__}: {str(error)[:300]}"
    else:
        payload = dict(result or {})
        confirmed = bool(payload.get("submission_confirmed"))
        outcome = "confirmed" if confirmed else "awaiting_confirmation"
        current_url = str(payload.get("current_url") or session.current_url or "")
        error_text = None

    approval.approval_metadata = {
        **metadata,
        "operator_submit_action_completed": error is None,
        "operator_submit_action_result": outcome,
        "operator_submit_action_finished_at": now.isoformat(),
        "operator_submit_confirmation_observed": confirmed,
        "operator_submit_current_url": current_url or None,
        "operator_submit_error": error_text,
        "automatic_retry_allowed": False,
    }
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type=(
                "operator_assisted_final_submit_action_observed"
                if error is None
                else "operator_assisted_final_submit_action_uncertain"
            ),
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "approval_reference": approval.reference,
                "handoff_public_id": session.public_id,
                "submission_confirmed": confirmed,
                "outcome": outcome,
                "current_url": current_url or None,
                "automatic_retry_allowed": False,
                "error": error_text,
            },
        )
    )
    db.flush()


__all__ = [
    "claim_operator_final_action",
    "finalize_operator_final_action",
]
