"""Conservative JT5 stale-attempt reconciliation.

Never republish a task or retry a browser action from this reconciler.
A queued message may have been delivered despite a lost broker acknowledgement.
An in-progress worker may have clicked Submit before crashing.
"""
from datetime import datetime, timedelta, timezone

from app.models.application import Application, ApplicationAutomationState
from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.services.application_state import transition_application_state


def reconcile_stale_jt5_attempts(db, *, now=None, stale_after_minutes=30, limit=100):
    """Mark stale JT5 attempts uncertain; retain the reservation and evidence."""
    if stale_after_minutes < 1:
        raise ValueError("stale_after_minutes must be positive")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=stale_after_minutes)
    candidates = (
        db.query(SubmissionAttempt)
        .filter(SubmissionAttempt.status.in_([
            SubmissionAttemptStatus.queued.value,
            SubmissionAttemptStatus.in_progress.value,
        ]))
        .order_by(SubmissionAttempt.id)
        .limit(limit)
        .all()
    )
    reconciled = []
    for candidate in candidates:
        attempt = (
            db.query(SubmissionAttempt)
            .filter(SubmissionAttempt.id == candidate.id)
            .with_for_update()
            .first()
        )
        if attempt is None or attempt.status not in (
            SubmissionAttemptStatus.queued.value,
            SubmissionAttemptStatus.in_progress.value,
        ):
            continue
        metadata = attempt.attempt_metadata or {}
        if metadata.get("execution_contract") != "jt5":
            continue
        timestamp = attempt.started_at or attempt.queued_at or attempt.created_at
        if timestamp is None:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if timestamp > cutoff:
            continue
        previous_status = attempt.status
        attempt.status = SubmissionAttemptStatus.uncertain.value
        attempt.completed_at = now.replace(tzinfo=None)
        attempt.attempt_metadata = {
            **metadata,
            "dispatch_status": "reconciliation_required",
            "reconciliation_reason": "stale_" + previous_status,
            "reconciled_at": now.isoformat(),
            "automatic_retry_allowed": False,
        }
        application = (
            db.query(Application)
            .filter(Application.id == attempt.application_id)
            .with_for_update()
            .first()
        )
        if application is not None and str(getattr(application.automation_state, "value", application.automation_state)) not in ("confirmed", "submitted"):
            transition_application_state(
                db, application, ApplicationAutomationState.submission_uncertain,
                "jt5_stale_attempt_requires_reconciliation",
                {"attempt_reference": attempt.reference},
            )
        reconciled.append(attempt.reference)
    db.commit()
    return reconciled
