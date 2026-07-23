import enum
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class HandoffSessionStatus(str, enum.Enum):
    awaiting_user = "awaiting_user"
    claimed = "claimed"
    ready_to_resume = "ready_to_resume"
    resuming = "resuming"
    completed = "completed"
    expired = "expired"
    cancelled = "cancelled"
    failed = "failed"


class HandoffChallengeType(str, enum.Enum):
    captcha = "captcha"
    mfa = "mfa"
    login = "login"
    anti_bot = "anti_bot"
    navigation = "navigation"


class HandoffActorType(str, enum.Enum):
    system = "system"
    user = "user"
    worker = "worker"


ACTIVE_HANDOFF_STATUSES = (
    HandoffSessionStatus.awaiting_user.value,
    HandoffSessionStatus.claimed.value,
    HandoffSessionStatus.ready_to_resume.value,
    HandoffSessionStatus.resuming.value,
)


def new_handoff_public_id() -> str:
    return str(uuid4())


class ManualHandoffSession(Base):
    __tablename__ = "manual_handoff_sessions"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(36), nullable=False, unique=True, index=True, default=new_handoff_public_id)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    manual_review_id = Column(Integer, ForeignKey("manual_review_tasks.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    challenge_type = Column(String(40), nullable=False, index=True)
    status = Column(
        String(40),
        nullable=False,
        default=HandoffSessionStatus.awaiting_user.value,
        index=True,
    )
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)

    # Resume and interaction secrets are never stored in plaintext.
    resume_token_hash = Column(String(64), nullable=False, index=True)
    encrypted_resume_token = Column(Text, nullable=False)
    resume_token_prefix = Column(String(16), nullable=False)
    resume_token_version = Column(Integer, nullable=False, default=1)
    resume_token_disclosed_at = Column(DateTime(timezone=True))
    resume_token_consumed_at = Column(DateTime(timezone=True))

    lease_token_hash = Column(String(64), nullable=True, index=True)
    encrypted_lease_token = Column(Text)
    lease_expires_at = Column(DateTime(timezone=True))
    claimed_at = Column(DateTime(timezone=True))
    last_heartbeat_at = Column(DateTime(timezone=True))
    lease_recovery_count = Column(Integer, nullable=False, default=0)

    browser_provider = Column(String(60), nullable=False, default="unavailable")
    browser_session_id = Column(String(255))
    encrypted_browser_endpoint = Column(Text)
    browser_node_id = Column(String(255))
    browser_process_id = Column(Integer)
    browser_profile_path = Column(String(1000))
    active_page_hint = Column(String(500))
    current_url = Column(String(1500))
    current_fingerprint = Column(String(128))
    storage_state_path = Column(String(1000))
    storage_state_hash = Column(String(128))
    screenshot_path = Column(String(1000))

    resume_attempt_count = Column(Integer, nullable=False, default=0)
    max_resume_attempts = Column(Integer, nullable=False, default=3)
    lock_version = Column(Integer, nullable=False, default=1)

    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ready_at = Column(DateTime(timezone=True))
    resumed_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    failure_reason = Column(Text)
    handoff_metadata = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    application = relationship("Application", back_populates="handoff_sessions")
    manual_review = relationship("ManualReviewTask", back_populates="handoff_sessions")
    user = relationship("User")
    events = relationship(
        "HandoffSessionEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="HandoffSessionEvent.created_at",
    )


class HandoffSessionEvent(Base):
    __tablename__ = "handoff_session_events"

    id = Column(Integer, primary_key=True, index=True)
    handoff_session_id = Column(
        Integer,
        ForeignKey("manual_handoff_sessions.id"),
        nullable=False,
        index=True,
    )
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    actor_type = Column(String(30), nullable=False, default=HandoffActorType.system.value)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    session = relationship("ManualHandoffSession", back_populates="events")