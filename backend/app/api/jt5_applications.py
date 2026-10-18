"""JT5 owner-authenticated Apply endpoint.

One action: reserve an attempt and dispatch the JT5 worker. No approval reference,
pilot flag, or secondary confirmation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application, ApplicationStatus
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.application_execution_gate import ApplyDecision
from app.tasks.jt5_execution import execute_reserved_application
from app.schemas.jt5_reconciliation import JT5OutcomeResolution
from app.services.jt5_outcome_resolution import JT5ResolutionError, resolution_context, resolve_jt5_outcome

router = APIRouter(prefix="/applications", tags=["applications-jt5"])

# Public owner status exposes enumerated operational codes, not raw metadata.
# Never echo arbitrary browser errors, internal exception messages, or secrets.
_RECONCILIATION_REASONS = frozenset({
    "stale_queued",
    "stale_in_progress",
    "worker_restarted_in_progress",
})

# The broker publish boundary stores type(exc).__name__, never its text.
# Only known operational exception categories are safe to surface to owners.
_DISPATCH_ERROR_TYPES = frozenset({
    "OperationalError",
    "ConnectionError",
    "TimeoutError",
    "OSError",
    "RuntimeError",
})


def _safe_jt5_attempt_diagnostics(attempt: SubmissionAttempt) -> dict:
    """Return owner-readable diagnostic identifiers without raw attempt metadata."""
    metadata = attempt.attempt_metadata
    if not isinstance(metadata, dict):
        metadata = {}
    dispatch_status = metadata.get("dispatch_status")
    if dispatch_status not in ("published", "worker_completed", "reconciliation_required"):
        dispatch_status = "unknown"
    if dispatch_status != "reconciliation_required":
        return {
            "dispatch_status": dispatch_status,
            "reconciliation_reason": None,
            "dispatch_error_type": None,
            "automatic_retry_allowed": False,
        }

    reason = metadata.get("reconciliation_reason")
    exception_type = metadata.get("dispatch_error_type")
    return {
        "dispatch_status": dispatch_status,
        "reconciliation_reason": reason if (
            isinstance(reason, str) and reason in _RECONCILIATION_REASONS
        ) else None,
        "dispatch_error_type": exception_type if (
            isinstance(exception_type, str) and exception_type in _DISPATCH_ERROR_TYPES
        ) else None,
        "automatic_retry_allowed": False,
    }



@router.get("/{application_id}/jt5/reconciliation")
def get_jt5_reconciliation(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read saved outcome evidence without starting any external action."""
    application = db.query(Application).filter(
        Application.id == application_id, Application.user_id == current_user.id,
    ).first()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return resolution_context(db, application)


@router.post("/{application_id}/jt5/reconcile")
def reconcile_jt5_application(
    application_id: int,
    data: JT5OutcomeResolution,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a reviewed outcome; never submit or queue another attempt."""
    try:
        result = resolve_jt5_outcome(db, application_id=application_id, user_id=current_user.id, data=data)
        db.commit()
        return result
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JT5ResolutionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OperationalError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) != "55P03":
            raise
        raise HTTPException(status_code=423, detail="This attempt is busy; no resolution was recorded") from exc


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
            **_safe_jt5_attempt_diagnostics(attempt),
            "attempt_number": attempt.attempt_number,
            "execution_contract": (
                "jt5" if isinstance(attempt.attempt_metadata, dict)
                and attempt.attempt_metadata.get("execution_contract") == "jt5"
                else None
            ),
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


@router.post("/{application_id}/jt5/apply")
def apply_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Owner Apply: reserve + dispatch JT5 worker in one request."""
    application = db.query(Application).filter(
        Application.id == application_id,
        Application.user_id == current_user.id,
    ).first()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status == ApplicationStatus.withdrawn:
        raise HTTPException(status_code=409, detail="Application is withdrawn")
    if not get_settings().allow_real_application_submit:
        raise HTTPException(status_code=503, detail="Live application submission is disabled")
    try:
        decision, attempt = reserve_jt5_attempt(
            db,
            application_id=application_id,
            authenticated_user_id=current_user.id,
        )
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
            .with_for_update()
            .first()
        )
        if reserved is not None:
            # Preserve the immutable reservation task identity. A worker may
            # already have claimed the attempt before broker ack returns.
            if reserved.status == "queued":
                reserved.attempt_metadata = {**(reserved.attempt_metadata or {}), "dispatch_status": "published", "published_at": datetime.utcnow().isoformat(), "broker_task_id": task_id}
            else:
                reserved.attempt_metadata = {**(reserved.attempt_metadata or {}), "broker_task_id": task_id}
            db.commit()
    except Exception as exc:
        db.rollback()
        try:
            reserved = db.query(SubmissionAttempt).filter(SubmissionAttempt.reference == attempt_reference).with_for_update().first()
            if reserved is not None:
                if reserved.status == "queued":
                    reserved.attempt_metadata = {**(reserved.attempt_metadata or {}), "dispatch_status": "reconciliation_required", "dispatch_error_type": type(exc).__name__}
                else:
                    reserved.attempt_metadata = {**(reserved.attempt_metadata or {}), "dispatch_error_type": type(exc).__name__}
                db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                "Attempt was reserved but queue publication failed. "
                "Check status; do not retry automatically."
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
