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
from app.services.application_attempt_integrity import install_application_attempt_result_guard
from app.services.application_state import normalize_state, transition_application_state
from app.services.handoff_session import cancel_handoff_session
from app.services.submission_integrity_integration import install_submission_integrity_guards


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
_TASK_GATE_INSTALLED = False
_TASK_GATE_ORIGINAL_RUN = None


def _value(value) -> str:
    return str(getattr(value, "value", value) or "")


def status_closes_submission(status: ApplicationStatus | str) -> bool:
    return _value(status) in _SUBMISSION_CLOSED_STATUSES


def submission_is_closed(application: Application) -> bool:
    return (
        status_closes_submission(application.status)
        or normalize_state(application.automation_state) in _SUBMISSION_CLOSED_STATES
    )


def closed_application_task_result(application: Application, *, dry_run: bool) -> dict:
    return {
        "success": True,
        "idempotent": True,
        "already_submitted": True,
        "dry_run": dry_run,
        "application_id": application.id,
        "status": _value(application.status),
        "state": normalize_state(application.automation_state),
        "submitted_at": application.applied_at.isoformat() if application.applied_at else None,
    }


def install_closed_application_task_gate() -> None:
    """Stop stale queued work before a browser or approval can be consumed.

    This gate must be installed after the supervised submission wrapper so a closed
    application returns idempotently before that wrapper validates or consumes a
    one-time live approval.
    """

    global _TASK_GATE_INSTALLED, _TASK_GATE_ORIGINAL_RUN
    install_application_attempt_result_guard()
    install_submission_integrity_guards()
    if _TASK_GATE_INSTALLED:
        return

    from app.tasks import applications as application_tasks

    task = application_tasks.submit_application_task
    _TASK_GATE_ORIGINAL_RUN = task.run

    def wrapped_run(application_id: int, dry_run: bool = True, **kwargs):
        db = application_tasks.SessionLocal()
        try:
            application = db.query(Application).filter(
                Application.id == application_id
            ).first()
            if application and submission_is_closed(application):
                return closed_application_task_result(application, dry_run=dry_run)
        finally:
            db.close()

        return _TASK_GATE_ORIGINAL_RUN(
            application_id,
            dry_run=dry_run,
            **kwargs,
        )

    task.run = wrapped_run
    _TASK_GATE_INSTALLED = True


def reconcile_user_reported_status(
    db: Session,
    application: Application,
    status: ApplicationStatus | str,
    *,
    user_id: int,
) -> List[ManualHandoffSession]:
    """Close submission machinery when a user records a terminal lifecycle status.

    A user-reported status is authoritative for queue closure, but it is not employer
    confirmation evidence. Therefore it must never fabricate ``submitted`` or
    ``confirmed`` automation states. Only the evidence pipeline may enter those states.
    """

    status_value = _value(status)
    if status_value not in _SUBMISSION_CLOSED_STATUSES:
        return []

    now = datetime.utcnow()
    current_state = normalize_state(application.automation_state)

    if status_value in _SUBMISSION_RECORDED_STATUSES:
        application.applied_at = application.applied_at or now
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="application_status_reconciled",
                from_state=current_state,
                to_state=current_state,
                payload={
                    "status": status_value,
                    "source": "user_status_update",
                    "submission_evidence_created": False,
                    "automation_state_inferred": False,
                },
            )
        )
    elif (
        status_value == ApplicationStatus.withdrawn.value
        and current_state not in {
            ApplicationAutomationState.submitted.value,
            ApplicationAutomationState.confirmed.value,
            ApplicationAutomationState.withdrawn.value,
        }
    ):
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.withdrawn,
            "application_status_reconciled",
            {
                "status": status_value,
                "source": "user_status_update",
                "submission_evidence_created": False,
                "automation_state_inferred": False,
            },
        )
    else:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="application_status_reconciled",
                from_state=current_state,
                to_state=current_state,
                payload={
                    "status": status_value,
                    "source": "user_status_update",
                    "submission_evidence_created": False,
                    "automation_state_inferred": False,
                },
            )
        )

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
