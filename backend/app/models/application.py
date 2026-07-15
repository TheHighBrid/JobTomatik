import enum
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    applying = "applying"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"


class ApplicationAutomationState(str, enum.Enum):
    preparing = "preparing"
    ready_to_apply = "ready_to_apply"
    applying = "applying"
    needs_review = "needs_review"
    submission_uncertain = "submission_uncertain"
    submitted = "submitted"
    confirmed = "confirmed"
    failed = "failed"
    withdrawn = "withdrawn"


class ManualReviewReason(str, enum.Enum):
    captcha_detected = "captcha_detected"
    anti_bot_challenge = "anti_bot_challenge"
    mfa_required = "mfa_required"
    assessment_required = "assessment_required"
    legal_answer_missing = "legal_answer_missing"
    sensitive_answer_missing = "sensitive_answer_missing"
    ambiguous_question = "ambiguous_question"
    unsupported_control = "unsupported_control"
    unsupported_platform = "unsupported_platform"
    login_required = "login_required"
    employer_contact_missing = "employer_contact_missing"
    submission_confirmation_uncertain = "submission_confirmation_uncertain"
    safety_gate_blocked = "safety_gate_blocked"
    missing_job_url = "missing_job_url"
    automation_error = "automation_error"


class ManualReviewStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    dismissed = "dismissed"


class SubmissionEvidenceType(str, enum.Enum):
    confirmation_page = "confirmation_page"
    success_banner = "success_banner"
    external_application_id = "external_application_id"
    portal_history = "portal_history"
    confirmation_email = "confirmation_email"
    email_provider_receipt = "email_provider_receipt"
    screenshot = "screenshot"
    html_snapshot = "html_snapshot"


def new_submission_idempotency_key() -> str:
    return str(uuid4())


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.pending)
    automation_state = Column(
        String(50),
        nullable=False,
        default=ApplicationAutomationState.preparing.value,
        index=True,
    )
    submission_idempotency_key = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        default=new_submission_idempotency_key,
    )
    submission_attempt_count = Column(Integer, nullable=False, default=0)
    last_submission_attempt_at = Column(DateTime(timezone=True))
    cover_letter = Column(Text)
    resume_path = Column(String(500))
    notes = Column(Text)
    applied_at = Column(DateTime(timezone=True))
    interview_at = Column(DateTime(timezone=True))
    offer_received_at = Column(DateTime(timezone=True))
    salary_offered = Column(Integer)
    rejection_reason = Column(Text)
    automation_log = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="applications")
    job = relationship("Job", back_populates="applications")
    followups = relationship("FollowUp", back_populates="application", cascade="all, delete-orphan")
    manual_reviews = relationship(
        "ManualReviewTask",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ManualReviewTask.created_at",
    )
    submission_evidence = relationship(
        "SubmissionEvidence",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="SubmissionEvidence.captured_at",
    )
    events = relationship(
        "ApplicationEvent",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.created_at",
    )


class FollowUp(Base):
    __tablename__ = "followups"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True))
    subject = Column(String(500))
    message = Column(Text)
    recipient_email = Column(String(255))
    status = Column(String(50), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    application = relationship("Application", back_populates="followups")


class ManualReviewTask(Base):
    __tablename__ = "manual_review_tasks"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    reason_code = Column(String(80), nullable=False, index=True)
    status = Column(String(30), nullable=False, default=ManualReviewStatus.open.value, index=True)
    summary = Column(Text, nullable=False)
    details = Column(JSON, default=dict)
    blocking_url = Column(String(1000))
    screenshot_path = Column(String(500))
    resume_token = Column(String(255))
    expires_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    application = relationship("Application", back_populates="manual_reviews")


class SubmissionEvidence(Base):
    __tablename__ = "submission_evidence"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    evidence_type = Column(String(80), nullable=False, index=True)
    is_sufficient = Column(Boolean, nullable=False, default=False, index=True)
    final_url = Column(String(1000))
    confirmation_text = Column(Text)
    selector = Column(String(500))
    external_application_id = Column(String(255))
    screenshot_path = Column(String(500))
    html_snapshot_path = Column(String(500))
    payload_hash = Column(String(128))
    evidence_metadata = Column(JSON, default=dict)
    captured_at = Column(DateTime(timezone=True), server_default=func.now())

    application = relationship("Application", back_populates="submission_evidence")


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    from_state = Column(String(50))
    to_state = Column(String(50))
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    application = relationship("Application", back_populates="events")
