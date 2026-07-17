from __future__ import annotations

import enum
import secrets

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class SubmissionEvidenceReviewDecision(str, enum.Enum):
    accepted = "accepted"
    rejected = "rejected"


def new_submission_evidence_review_reference() -> str:
    return "ghev-" + secrets.token_urlsafe(18)


class SubmissionEvidenceReview(Base):
    """Immutable human review of one concrete submission-evidence record.

    The record stores only hashes, references, the decision, and reviewer notes.
    It never copies applicant answers, browser credentials, or raw form payloads.
    A later evidence mutation invalidates the review because the recorded snapshot
    hash will no longer match.
    """

    __tablename__ = "submission_evidence_reviews"
    __table_args__ = (
        UniqueConstraint("evidence_id", "evidence_snapshot_hash", name="uq_evidence_review_snapshot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(
        String(96),
        nullable=False,
        unique=True,
        index=True,
        default=new_submission_evidence_review_reference,
    )
    application_id = Column(
        Integer,
        ForeignKey("applications.id"),
        nullable=False,
        index=True,
    )
    evidence_id = Column(
        Integer,
        ForeignKey("submission_evidence.id"),
        nullable=False,
        index=True,
    )
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approval_reference = Column(String(96), nullable=True, index=True)
    decision = Column(String(24), nullable=False, index=True)
    evidence_snapshot_hash = Column(String(64), nullable=False)
    application_payload_hash = Column(String(64), nullable=True)
    review_notes = Column(Text)
    review_metadata = Column(JSON, default=dict)
    reviewed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
