"""
JT5 task reservation claim and result reconciliation helpers.

This module keeps the state transition independent of legacy approval records.
"""
from datetime import datetime

from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.services.submission_integrity import finalize_submission_attempt


def claim_jt5_attempt(db, application_id: int, reference: str):
    attempt = (
        db.query(SubmissionAttempt)
        .filter(
            SubmissionAttempt.application_id == application_id,
            SubmissionAttempt.reference == reference,
        )
        .with_for_update()
        .first()
    )
    if not attempt or (attempt.attempt_metadata or {}).get("execution_contract") != "jt5":
        return None
    if attempt.status != SubmissionAttemptStatus.queued.value:
        return None
    attempt.status = SubmissionAttemptStatus.in_progress.value
    attempt.started_at = datetime.utcnow()
    db.flush()
    return attempt


def complete_jt5_attempt(db, attempt, *, outcome: str, details=None):
    statuses = {
        "confirmed": SubmissionAttemptStatus.succeeded,
        "failed_pre_submit": SubmissionAttemptStatus.failed,
        "submission_uncertain": SubmissionAttemptStatus.uncertain,
    }
    if outcome not in statuses:
        raise ValueError("invalid_jt5_outcome")
    return finalize_submission_attempt(
        db,
        attempt,
        status=statuses[outcome],
        result={"outcome": outcome, **(details or {})},
    )
