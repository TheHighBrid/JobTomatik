"""JT5 transactional attempt reservation without a human approval ceremony.

The legacy schema requires approval_reference, binding_hash and payload_hash.
For compatibility until a schema migration, these fields receive internal
attempt-specific values, never a user approval token.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.submission_integrity import (
    SubmissionAttempt,
    SubmissionAttemptStatus,
)
from app.models.job import Job
from app.services.application_target import initialize_application_target
from app.services.application_execution_gate import (
    ApplyDecision,
    ApplyGateResult,
    decide_application_execution,
)
from app.services.submission_integrity import (
    active_submission_attempt,
    application_identity_digest,
)


def reserve_jt5_attempt(
    db: Session,
    *,
    application_id: int,
    authenticated_user_id: int,
) -> tuple[ApplyGateResult, SubmissionAttempt | None]:
    """Reserve while holding the application row lock; caller commits transaction.

    A worker must claim the returned attempt before browser execution. Do not
    publish before commit. Reconcile uncertain outcomes rather than retrying.
    """
    application = (
        db.query(Application)
        .filter(Application.id == application_id)
        .with_for_update()
        .first()
    )
    if application is None:
        raise LookupError("application_not_found")

    active = active_submission_attempt(db, application.id)
    decision = decide_application_execution(
        authenticated_user_id=authenticated_user_id,
        application_owner_id=application.user_id,
        application_state=str(getattr(application.automation_state, "value", application.automation_state) or ""),
        has_active_attempt=active is not None,
    )
    latest_status = (
        db.query(SubmissionAttempt.status)
        .filter(SubmissionAttempt.application_id == application.id)
        .order_by(SubmissionAttempt.id.desc())
        .first()
    )
    if latest_status and latest_status[0] == SubmissionAttemptStatus.succeeded.value:
        return ApplyGateResult(ApplyDecision.ALREADY_CONFIRMED, "existing_submission"), None
    if latest_status and latest_status[0] == SubmissionAttemptStatus.uncertain.value:
        return ApplyGateResult(ApplyDecision.RECONCILE, "prior_outcome_uncertain"), None
    if decision.decision is not ApplyDecision.EXECUTE:
        return decision, active

    # Resolve direct ATS URLs before freezing the immutable JT5 reservation.\n    # Listing-only sources remain unresolved and cannot be silently treated as apply URLs.\n    job = db.query(Job).filter(Job.id == application.job_id).first()\n    if job is not None:\n        initialize_application_target(db, application, job)\n\n    # A failed pre-submit attempt is retryable; a confirmed or uncertain one is not.
    # Database uniqueness plus the locked application row protects attempt numbers.

    # Keep the attempt counter synchronized with the durable attempt history.
    latest = (
        db.query(SubmissionAttempt.attempt_number)
        .filter(SubmissionAttempt.application_id == application.id)
        .order_by(SubmissionAttempt.attempt_number.desc())
        .first()
    )
    number = max(int(application.submission_attempt_count or 0), int(latest[0]) if latest else 0) + 1
    internal_reference = "jt5-" + uuid4().hex
    identity = application_identity_digest(db, application)
    binding = hashlib.sha256(f"{application.id}:{number}:{identity}".encode()).hexdigest()
    attempt = SubmissionAttempt(
        application_id=application.id,
        user_id=application.user_id,
        reference=internal_reference,
        approval_reference=internal_reference,  # Legacy non-null column; not an approval.
        attempt_number=number,
        task_id="reserved-" + uuid4().hex,
        status=SubmissionAttemptStatus.queued.value,
        binding_hash=binding,
        identity_digest=identity,
        combined_payload_hash=binding,
        attempt_metadata={
            "execution_contract": "jt5",
            "automatic_retry_allowed": False,
            "reserved_target_url": str(application.application_target_url or "").strip(),
        },
    )
    db.add(attempt)
    db.flush()
    application.submission_attempt_count = number
    return decision, attempt
