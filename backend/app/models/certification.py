from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class CertificationEvidence(Base):
    """Immutable-ish retained evidence used by the Phase 10 release evaluator.

    The payload hash binds the submitted evidence metadata. Review state is kept
    separately so recording evidence can never imply that it has been independently
    verified. Evidence can be revoked or expire without deleting its audit history.
    """

    __tablename__ = "certification_evidence"

    id = Column(Integer, primary_key=True, index=True)
    evidence_key = Column(String(255), nullable=False, unique=True, index=True)
    evidence_type = Column(String(80), nullable=False, index=True)
    adapter = Column(String(80), nullable=True, index=True)
    commit_sha = Column(String(64), nullable=False, index=True)
    environment = Column(String(80), nullable=False, default="unknown", index=True)
    status = Column(String(40), nullable=False, default="recorded", index=True)
    duration_seconds = Column(Integer, nullable=True)
    source_reference = Column(String(1000), nullable=False)
    payload_hash = Column(String(128), nullable=False, index=True)
    evidence_metadata = Column(JSON, default=dict)
    recorded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    review_status = Column(String(40), nullable=False, default="unreviewed", index=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_reference = Column(String(1000), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ReleaseAuthorization(Base):
    """Commit-bound owner authorization that never toggles runtime submission flags."""

    __tablename__ = "release_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "approved_by_user_id",
            "approval_reference",
            name="uq_release_authorization_owner_reference",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(80), nullable=False, index=True)
    release_version = Column(String(80), nullable=False, index=True)
    commit_sha = Column(String(64), nullable=False, index=True)
    approval_reference = Column(String(255), nullable=False, index=True)
    payload_hash = Column(String(128), nullable=False)
    status = Column(String(40), nullable=False, default="approved", index=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    authorization_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
