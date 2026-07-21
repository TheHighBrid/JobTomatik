from __future__ import annotations

import enum
import secrets

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.database import Base


class SubmissionApprovalStatus(str, enum.Enum):
    active = "active"
    consumed = "consumed"
    revoked = "revoked"
    expired = "expired"


def new_platform_submission_approval_reference(platform: str) -> str:
    normalized = str(platform or "").strip().lower()
    prefix = {
        "greenhouse": "ghsup",
        "lever": "lvsup",
    }.get(normalized, "sup")
    return prefix + "-" + secrets.token_urlsafe(18)


def new_submission_approval_reference(context=None) -> str:
    """Generate a platform-scoped reference while preserving Greenhouse history."""
    platform = "greenhouse"
    if context is not None:
        parameters = context.get_current_parameters()
        platform = str(parameters.get("platform") or platform)
    return new_platform_submission_approval_reference(platform)


class SubmissionApproval(Base):
    """One-time, exact-payload approval for a supervised real submission.

    The record contains hashes and immutable target snapshots, never applicant
    answers or browser credentials. An approval is consumed before a live worker
    starts, so a crash requires a fresh explicit approval rather than an unsafe
    automatic retry.
    """

    __tablename__ = "submission_approvals"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(
        String(96),
        nullable=False,
        unique=True,
        index=True,
        default=new_submission_approval_reference,
    )
    application_id = Column(
        Integer,
        ForeignKey("applications.id"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    platform = Column(String(80), nullable=False, index=True)
    status = Column(
        String(30),
        nullable=False,
        default=SubmissionApprovalStatus.active.value,
        index=True,
    )

    employer = Column(String(500), nullable=False)
    role = Column(String(500), nullable=False)
    application_url = Column(String(1500), nullable=False)
    submission_idempotency_key = Column(String(255), nullable=False)

    profile_snapshot_hash = Column(String(64), nullable=False)
    resume_hash = Column(String(64), nullable=False)
    cover_letter_hash = Column(String(64), nullable=False)
    answer_payload_hash = Column(String(64), nullable=False)
    combined_payload_hash = Column(String(64), nullable=False)

    approved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    approval_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
