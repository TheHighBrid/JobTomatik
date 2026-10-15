"""Conservative JT5 stale-attempt reconciliation.

Never republish a task or retry a browser action from this reconciler.
A queued message may have been delivered despite a lost broker acknowledgement.
An in-progress worker may have clicked Submit before crashing.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.models.application import Application, ApplicationAutomationState
from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.services.application_state import transition_application_state


def reconcile_stale_jt5_attempts(
    db, *, now=None, stale_after_minutes=30, limit=100,
    worker_restarted=False, commit=True,
):
    """Reconcile stale attempts or claims whose sole owning worker has stopped.

    Only the OneHost startup path may assert worker_restarted. A fresh queued
    message remains claimable; an interrupted claim is uncertain at any age.
    commit=False lets startup keep all recovery changes in its own transaction.
    """
    if stale_after_minutes < 1:
        raise ValueError("stale_after_minutes must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")
    now = now or datetime.now(timezone.utc)
    now = (
        now.replace(tzinfo=timezone.utc)
        if now.tzinfo is None else now.astimezone(timezone.utc)
    )
    cutoff = now - timedelta(minutes=stale_after_minutes)
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
    candidates = (
        db.query(SubmissionAttempt)
        .filter(
            SubmissionAttempt.attempt_metadata["execution_contract"].as_string() == "jt5"
        )
        .filter(SubmissionAttempt.status.in_([
            SubmissionAttemptStatus.queued.value,
            SubmissionAttemptStatus.in_progress.value,
        ]))
        .filter(eligible)
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
            .populate_existing()
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
        previous_status = attempt.status
        interrupted = (
            worker_restarted
            and previous_status == SubmissionAttemptStatus.in_progress.value
        )
        if not interrupted:
            timestamp = attempt.started_at or attempt.queued_at or attempt.created_at
            if timestamp is None:
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp > cutoff:
                continue
        attempt.status = SubmissionAttemptStatus.uncertain.value
        attempt.completed_at = now.replace(tzinfo=None)
        attempt.attempt_metadata = {
            **metadata,
            "dispatch_status": "reconciliation_required",
            "reconciliation_reason": (
                "worker_restarted_in_progress" if interrupted else "stale_" + previous_status
            ),
            "reconciled_at": now.isoformat(),
            "automatic_retry_allowed": False,
        }
        application = (
            db.query(Application)
            .filter(Application.id == attempt.application_id)
            .with_for_update()
            .first()
        )
        if application is not None and str(
            getattr(application.automation_state, "value", application.automation_state)
        ) not in ("confirmed", "submitted"):
            transition_application_state(
                db, application, ApplicationAutomationState.submission_uncertain,
                (
                    "jt5_worker_restart_requires_reconciliation"
                    if interrupted else "jt5_stale_attempt_requires_reconciliation"
                ),
                {"attempt_reference": attempt.reference},
            )
        reconciled.append(attempt.reference)
    if commit:
        db.commit()
    else:
        db.flush()
    return reconciled
