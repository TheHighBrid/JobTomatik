from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import ACTIVE_HANDOFF_STATUSES, ManualHandoffSession
from app.services.application_state import normalize_state
from app.services.handoff_session import cancel_handoff_session


_SUBMISSION_RECORDED_STATUSES = {
    ApplicationStatus.applied.value,
    ApplicationStatus.interviewing.value,
    ApplicationStatus.offer.value,
    ApplicationStatus.rejected.value,
}
_SUBMISSION_CLOSED_STATUSES = {
    *_SUBMISSION_RECORDED_STATUSES,
    ApplicationStatus.withdrawn.value,
}
_SUBMISSION_CLOSED_STATES = {
    ApplicationAutomationState.submitted.value,
    ApplicationAutomationState.confirmed.value,
    ApplicationAutomationState.withdrawn.value,
}


def _value(value) -> str:
    return str(getattr(value, "value", value) or "")


def submission_is_closed(application: Application) -> bool:
    return (
        _value(application.status) in _SUBMISSION_CLOSED_STATUSES
        or normalize_state(application.automation_state) in _SUBMISSION_CLOSED_STATES
    )


def reconcile_user_reported_status(
    db: Session,
    application: Application,
    status: ApplicationStatus | str,
    *,
    user_id: int,
) -> List[ManualHandoffSession]:
    """Close submission machinery when a user records a terminal lifecycle status.

    This is an explicit user status reconciliation, not employer confirmation evidence.
    Employer-confirmed flows continue to use the submission-evidence pipeline.
    """

    status_value = _value(status)
    if status_value not in _SUBMISSION_CLOSED_STATUSES:
        return []

    now = datetime.utcnow()
    current_state = normalize_state(application.automation_state)
    target_state = current_state

    if status_value in _SUBMISSION_RECORDED_STATUSES:
        application.applied_at = application.applied_at or now
        if current_state not in {
            ApplicationAutomationState.submitted.value,
            ApplicationAutomationState.confirmed.value,
        }:
            target_state = ApplicationAutomationState.submitted.value
    elif (
        status_value == ApplicationStatus.withdrawn.value
        and current_state not in {
            ApplicationAutomationState.submitted.value,
            ApplicationAutomationState.confirmed.value,
            ApplicationAutomationState.withdrawn.value,
        }
    ):
        target_state = ApplicationAutomationState.withdrawn.value

    if target_state != current_state:
        application.automation_state = target_state
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="application_status_reconciled",
            from_state=current_state,
            to_state=target_state,
            payload={
                "status": status_value,
                "source": "user_status_update",
                "submission_evidence_created": False,
            },
        ))

    reviews = (
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
    for review in reviews:
        review.status = ManualReviewStatus.dismissed.value
        review.resolved_at = now
        review.resolution_notes = (
            f"Closed because the application was manually recorded as {status_value}."
        )

    sessions = (
        db.query(ManualHandoffSession)
        .filter(
            ManualHandoffSession.application_id == application.id,
            ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
        )
        .all()
    )
    for session in sessions:
        cancel_handoff_session(
            db,
            session,
            user_id=user_id,
            reason=f"Application manually recorded as {status_value}.",
        )

    return sessions
