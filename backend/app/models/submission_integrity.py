from __future__ import annotations

import enum
import secrets

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class SubmissionAttemptStatus(str, enum.Enum):
    queued = "queued"
    in_progress = "in_progress"
    succeeded = "succeeded"
    uncertain = "uncertain"
    blocked = "blocked"
    failed = "failed"


ACTIVE_SUBMISSION_ATTEMPT_STATUSES = (
    SubmissionAttemptStatus.queued.value,
    SubmissionAttemptStatus.in_progress.value,
    SubmissionAttemptStatus.uncertain.value,
)


def new_submission_attempt_reference() -> str:
    return "attempt-" + secrets.token_urlsafe(18)


class SubmissionIdentityAlias(Base):
    """One durable identity for a posting/application pair.

    A single application may own several aliases: source listing, source external ID,
    canonical ATS posting identity, canonical employer target, and redirect target.
    The user-scoped uniqueness constraint prevents two application rows from owning
    the same posting identity even when discovery produced different Job records.
    """

    __tablename__ = "submission_identity_aliases"
    __table_args__ = (
        UniqueConstraint("user_id", "alias_key", name="uq_submission_identity_user_alias"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    alias_type = Column(String(80), nullable=False, index=True)
    alias_key = Column(String(64), nullable=False, index=True)
    canonical_value = Column(String(2000), nullable=False)
    alias_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SubmissionAttempt(Base):
    """One immutable queue/final-submit reservation.

    The unique approval reference and application/attempt number constraints make a
    double click, duplicate queue message, worker restart, or concurrent worker an
    idempotent replay rather than a second final action.
    """

    __tablename__ = "submission_attempts"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "attempt_number",
            name="uq_submission_attempt_application_number",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(
        String(96),
        nullable=False,
        unique=True,
        index=True,
        default=new_submission_attempt_reference,
    )
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approval_reference = Column(String(96), nullable=False, unique=True, index=True)
    attempt_number = Column(Integer, nullable=False)
    task_id = Column(String(96), nullable=False, unique=True, index=True)
    status = Column(
        String(30),
        nullable=False,
        default=SubmissionAttemptStatus.queued.value,
        index=True,
    )
    binding_hash = Column(String(64), nullable=False, index=True)
    identity_digest = Column(String(64), nullable=False, index=True)
    combined_payload_hash = Column(String(64), nullable=False)
    adapter_version = Column(String(100))
    target_identity_hash = Column(String(64))
    attempt_metadata = Column(JSON, default=dict)
    queued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SubmissionEvidenceReceipt(Base):
    """Replay receipt for confirmation pages, emails, provider IDs, and payloads."""

    __tablename__ = "submission_evidence_receipts"

    id = Column(Integer, primary_key=True, index=True)
    fingerprint = Column(String(64), nullable=False, unique=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("submission_evidence.id"), unique=True, index=True)
    evidence_type = Column(String(80), nullable=False, index=True)
    external_application_id = Column(String(255))
    payload_hash = Column(String(128))
    final_url = Column(String(1000))
    receipt_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
