"""OneHost production resilience bookkeeping.

These checks model the failures that happen between API, worker, Redis,
Postgres, and the owned browser. They do not submit an application and they
do not treat a restart as confirmation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    SubmissionEvidence,
)


class OneHostResilienceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _event(db: Session, application: Application, event_type: str, payload: Dict[str, Any]) -> None:
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type=event_type,
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload=payload,
        )
    )


def _sufficient_evidence(db: Session, application_id: int) -> Optional[SubmissionEvidence]:
    return (
        db.query(SubmissionEvidence)
        .filter(
            SubmissionEvidence.application_id == application_id,
            SubmissionEvidence.is_sufficient.is_(True),
        )
        .first()
    )


def recover_after_api_restart(db: Session, application_id: int) -> Dict[str, Any]:
    application = db.query(Application).filter(Application.id == application_id).one()
    _event(db, application, "onehost_api_restart_state_preserved", {"application_id": application.id})
    db.flush()
    return {
        "application_id": application.id,
        "status": application.status.value if hasattr(application.status, "value") else str(application.status),
        "automation_state": application.automation_state,
        "state_preserved": True,
        "submit_attempted": False,
    }


def recover_after_worker_restart(
    db: Session,
    application_id: int,
    *,
    approval_consumed: bool,
) -> Dict[str, Any]:
    application = db.query(Application).filter(Application.id == application_id).one()
    evidence = _sufficient_evidence(db, application.id)
    if approval_consumed and evidence is None:
        application.automation_state = ApplicationAutomationState.submission_uncertain.value
        _event(db, application, "onehost_worker_replay_suppressed", {
            "reason": "consumed_approval_without_evidence",
            "duplicate_application": False,
        })
        db.flush()
        return {
            "application_id": application.id,
            "duplicate_application": False,
            "automation_state": application.automation_state,
            "submit_attempted": False,
        }
    _event(db, application, "onehost_worker_restart_noop", {"duplicate_application": False})
    db.flush()
    return {
        "application_id": application.id,
        "duplicate_application": False,
        "automation_state": application.automation_state,
        "submit_attempted": False,
    }


def recover_after_browser_crash(db: Session, application_id: int) -> Dict[str, Any]:
    application = db.query(Application).filter(Application.id == application_id).one()
    evidence = _sufficient_evidence(db, application.id)
    if evidence is None and application.automation_state == ApplicationAutomationState.confirmed.value:
        raise OneHostResilienceError("untruthful_confirmed_state", "Confirmed state has no sufficient evidence")
    if evidence is None and application.status == ApplicationStatus.applied:
        raise OneHostResilienceError("untruthful_applied_state", "Applied state has no sufficient evidence")
    if evidence is None and application.automation_state == ApplicationAutomationState.applying.value:
        application.automation_state = ApplicationAutomationState.submission_uncertain.value
    _event(db, application, "onehost_browser_crash_recovered", {
        "truthful": evidence is not None or application.status != ApplicationStatus.applied,
    })
    db.flush()
    return {
        "application_id": application.id,
        "automation_state": application.automation_state,
        "confirmed": application.automation_state == ApplicationAutomationState.confirmed.value,
        "submit_attempted": False,
    }


def recover_after_redis_loss(db: Session, application_id: int, *, queued_task_id: Optional[str]) -> Dict[str, Any]:
    application = db.query(Application).filter(Application.id == application_id).one()
    evidence = _sufficient_evidence(db, application.id)
    if queued_task_id and evidence is None:
        if application.status == ApplicationStatus.applied:
            raise OneHostResilienceError("phantom_submission", "Redis loss cannot invent a submission")
        application.automation_state = ApplicationAutomationState.needs_review.value
        _event(db, application, "onehost_redis_loss_no_phantom_submission", {"queued_task_id": queued_task_id})
        db.flush()
    return {
        "application_id": application.id,
        "phantom_submission": False,
        "automation_state": application.automation_state,
        "submit_attempted": False,
    }


def recover_after_confirmation_crash(db: Session, application_id: int) -> Dict[str, Any]:
    application = db.query(Application).filter(Application.id == application_id).one()
    evidence = _sufficient_evidence(db, application.id)
    if evidence is None:
        application.automation_state = ApplicationAutomationState.submission_uncertain.value
        _event(db, application, "onehost_confirmation_crash_uncertain", {"reason": "evidence_missing"})
        db.flush()
        return {"application_id": application.id, "confirmed": False, "automation_state": application.automation_state}
    application.status = ApplicationStatus.applied
    application.automation_state = ApplicationAutomationState.confirmed.value
    application.applied_at = application.applied_at or datetime.utcnow()
    _event(db, application, "onehost_confirmation_crash_reconciled", {"evidence_id": evidence.id})
    db.flush()
    return {
        "application_id": application.id,
        "confirmed": True,
        "automation_state": application.automation_state,
        "submit_attempted": False,
    }
