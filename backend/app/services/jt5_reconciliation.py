"""
Conservative JT5 stale-attempt reconciliation.

Never republish a task or retry a browser action from this reconciler.
A queued message may have been delivered despite a lost broker acknowledgement.
An in-progress worker may have clicked Submit before crashing.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.models.application import Application, ApplicationAutomationState
from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.services.application_state import (
    application_state_transition_manifest,
    normalize_state,
    transition_application_state,
)

_RECOVERABLE_STATUSES = (
    SubmissionAttemptStatus.queued.value,
    SubmissionAttemptStatus.in_progress.value,
)


def _utc(timestamp):
    return (
        timestamp.replace(tzinfo=timezone.utc)
        if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
    )


def _recovery_candidates(db, cutoff, worker_restarted, limit):
    stale = func.coalesce(
        SubmissionAttempt.started_at,
        SubmissionAttempt.queued_at,
        SubmissionAttempt.created_at,
    ) <= cutoff
    eligible = stale
    if worker_restarted:
        eligible = stale | (
            SubmissionAttempt.status == SubmissionAttemptStatus.in_progress.value
        )
    return (
        db.query(SubmissionAttempt)
        .filter(
            SubmissionAttempt.attempt_metadata["execution_contract"].as_string() == "jt5",
            SubmissionAttempt.status.in_(_RECOVERABLE_STATUSES),
            eligible,
        )
        .order_by(SubmissionAttempt.id)
        .limit(limit)
        .all()
    )


def _active_jt5_attempt(attempt):
    if attempt is None:
        return False
    return (
        attempt.status in _RECOVERABLE_STATUSES
        and (attempt.attempt_metadata or {}).get("execution_contract") == "jt5"
    )


def _reconciliation_reason(attempt, cutoff, worker_restarted):
    if not _active_jt5_attempt(attempt):
        return None
    if worker_restarted and attempt.status == SubmissionAttemptStatus.in_progress.value:
        return "worker_restarted_in_progress"
    timestamp = attempt.started_at or attempt.queued_at or attempt.created_at
    if timestamp is None:
        return None
    if _utc(timestamp) > cutoff:
        return None
    return "stale_" + attempt.status


def _mark_uncertain(db, attempt, now, reason):
    attempt.status = SubmissionAttemptStatus.uncertain.value
    attempt.completed_at = now.replace(tzinfo=None)
    attempt.attempt_metadata = {
        **(attempt.attempt_metadata or {}),
        "dispatch_status": "reconciliation_required",
        "reconciliation_reason": reason,
        "reconciled_at": now.isoformat(),
        "automatic_retry_allowed": False,
    }
    application = (
        db.query(Application)
        .filter(Application.id == attempt.application_id)
        .with_for_update()
        .first()
    )
    if application is None:
        return
    state = normalize_state(application.automation_state)
    if state in ("confirmed", "submitted"):
        return
    target_state = ApplicationAutomationState.submission_uncertain.value
    allowed = application_state_transition_manifest()["allowed_transitions"].get(state, [])
    # Reconcile the attempt without overwriting a review, withdrawal, or other
    # state for which the canonical lifecycle does not allow this transition.
    if state != target_state and target_state not in allowed:
        return
    event = (
        "jt5_worker_restart_requires_reconciliation"
        if reason == "worker_restarted_in_progress"
        else "jt5_stale_attempt_requires_reconciliation"
    )
    transition_application_state(
        db, application, ApplicationAutomationState.submission_uncertain,
        event, {"attempt_reference": attempt.reference},
    )


def reconcile_stale_jt5_attempts(
    db, *, now=None, stale_after_minutes=30, limit=100,
    worker_restarted=False, commit=True,
):
    """
    Reconcile stale attempts or claims whose sole owning worker has stopped.

    Only the OneHost startup path may assert worker_restarted. A fresh queued
    message remains claimable; an interrupted claim is uncertain at any age.
    commit=False lets startup keep all recovery changes in its own transaction.
    """
    if stale_after_minutes < 1:
        raise ValueError("stale_after_minutes must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")
    now = _utc(now or datetime.now(timezone.utc))
    cutoff = now - timedelta(minutes=stale_after_minutes)
    candidates = _recovery_candidates(db, cutoff, worker_restarted, limit)
    reconciled = []
    for candidate in candidates:
        attempt = (
            db.query(SubmissionAttempt)
            .filter(SubmissionAttempt.id == candidate.id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        reason = _reconciliation_reason(attempt, cutoff, worker_restarted)
        if reason is None:
            continue
        _mark_uncertain(db, attempt, now, reason)
        reconciled.append(attempt.reference)
    if commit:
        db.commit()
    else:
        db.flush()
    return reconciled
