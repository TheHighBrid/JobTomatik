from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class LivePilotAuthorization(Base):
    """Short-lived owner authority for one exact promoted live-pilot revision."""

    __tablename__ = "live_pilot_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "approved_by_user_id",
            "approval_reference",
            name="uq_live_pilot_authorization_owner_reference",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    adapter = Column(String(80), nullable=False, index=True)
    adapter_version = Column(String(80), nullable=False)
    commit_sha = Column(String(64), nullable=False, index=True)
    approval_reference = Column(String(255), nullable=False, index=True)
    payload_hash = Column(String(128), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="approved", index=True)
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    max_submission_attempts = Column(Integer, nullable=False)
    reserved_submission_attempts = Column(Integer, nullable=False, default=0)
    approved_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    authorization_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class LivePilotAttemptReservation(Base):
    """Durable non-reclaiming reservation for one application live-submit attempt."""

    __tablename__ = "live_pilot_attempt_reservations"
    __table_args__ = (
        UniqueConstraint(
            "authorization_id",
            "application_id",
            name="uq_live_pilot_authorization_application",
        ),
        UniqueConstraint(
            "application_id",
            name="uq_live_pilot_application_reservation",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    authorization_id = Column(
        Integer,
        ForeignKey("live_pilot_authorizations.id"),
        nullable=False,
        index=True,
    )
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    reservation_key = Column(String(255), nullable=False, unique=True, index=True)
    reserved_at = Column(DateTime(timezone=True), nullable=False, index=True)
    reservation_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


__all__ = ["LivePilotAuthorization", "LivePilotAttemptReservation"]
