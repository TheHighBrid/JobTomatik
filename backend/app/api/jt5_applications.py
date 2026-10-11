"""JT5 owner-authenticated Apply endpoint.

One action: reserve an attempt and dispatch the JT5 worker. No approval reference,
pilot flag, or secondary confirmation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.application_execution_gate import ApplyDecision
from app.tasks.jt5_execution import execute_reserved_application

router = APIRouter(prefix="/applications", tags=["applications-jt5"])


@router.get("/{application_id}/jt5/status")
def jt5_status(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read-only status for owner monitoring. Does not reserve or dispatch."""
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == current_user.id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    attempt = (
        db.query(SubmissionAttempt)
        .filter(SubmissionAttempt.application_id == application_id)
        .order_by(SubmissionAttempt.id.desc())
        .first()
    )
    attempt_payload = None
    if attempt is not None:
        attempt_payload = {
            "reference": attempt.reference,
            "status": attempt.status,
            "task_id": attempt.task_id,
            "attempt_number": attempt.attempt_number,
            "execution_contract": (attempt.attempt_metadata or {}).get("execution_contract"),
            "queued_at": attempt.queued_at.isoformat() if attempt.queued_at else None,
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        }

    return {
        "application_id": application_id,
        "automation_state": application.automation_state,
        "status": application.status.value if hasattr(application.status, "value") else application.status,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
        "latest_attempt": attempt_payload,
        "execution_contract": "jt5",
        "automatic_retry_allowed": False,
    }


@router.post("/{application_id}/jt5/reserve")
def reserve_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reserve only (no dispatch). Useful for tests and staged rollout."""
    try:
        decision, attempt = reserve_jt5_attempt(
            db,
            application_id=application_id,
            authenticated_user_id=current_user.id,
        )
        db.commit()
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Application not found") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Concurrent reservation; reload application status",
        ) from None

    if decision.decision is ApplyDecision.FORBIDDEN:
        raise HTTPException(status_code=404, detail="Application not found")
    if decision.decision is ApplyDecision.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="Authentication required")
    if decision.decision is not ApplyDecision.EXECUTE:
        return {
            "status": decision.decision.value,
            "reason": decision.reason,
            "application_id": application_id,
        }
    return {
        "status": "reserved",
        "application_id": application_id,
        "attempt_reference": attempt.reference,
        "task_id": attempt.task_id,
        "dispatch_status": "not_dispatched",
        "execution_contract": "jt5",
    }


@router.post("/{application_id}/jt5/apply")
def apply_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Owner Apply: reserve + dispatch JT5 worker in one request."""
    try:
        decision, attempt = reserve_jt5_attempt(
            db,
            application_id=application_id,
            authenticated_user_id=current_user.id,
        )
        if decision.decision is ApplyDecision.FORBIDDEN:
            db.rollback()
            raise HTTPException(status_code=404, detail="Application not found")
        if decision.decision is ApplyDecision.AUTH_REQUIRED:
            db.rollback()
            raise HTTPException(status_code=401, detail="Authentication required")
        if decision.decision is not ApplyDecision.EXECUTE:
            db.commit()
            return {
                "status": decision.decision.value,
                "reason": decision.reason,
                "application_id": application_id,
            }

        attempt_reference = attempt.reference
        db.commit()
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Application not found") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Concurrent reservation; reload application status",
        ) from None

    try:
        async_result = execute_reserved_application.apply_async(
            args=[application_id, attempt_reference],
            queue="applications",
        )
        task_id = str(async_result.id)
        reserved = (
            db.query(SubmissionAttempt)
            .filter(SubmissionAttempt.reference == attempt_reference)
            .first()
        )
        if reserved is not None:
            reserved.task_id = task_id
            db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                "Attempt was reserved but queue publication failed. "
                "Do not re-apply until the attempt is reconciled. "
                f"{type(exc).__name__}"
            ),
        ) from exc

    return {
        "status": "queued",
        "application_id": application_id,
        "attempt_reference": attempt_reference,
        "task_id": task_id,
        "dispatch_status": "dispatched",
        "execution_contract": "jt5",
        "automatic_retry_allowed": False,
    }
