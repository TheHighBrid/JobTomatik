import enum

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AnswerPolicyMode(str, enum.Enum):
    answer = "answer"
    decline = "decline"
    ask_each_time = "ask_each_time"
    skip = "skip"


class AnswerPolicyScope(str, enum.Enum):
    global_scope = "global"
    platform = "platform"
    company = "company"


class AnswerPolicyProvenance(str, enum.Enum):
    user_provided = "user_provided"
    verified_import = "verified_import"
    ai_suggested = "ai_suggested"
    unknown = "unknown"


class ApplicantAnswerPolicy(Base):
    __tablename__ = "applicant_answer_policies"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "canonical_key",
            "scope",
            "scope_value",
            name="uq_answer_policy_user_key_scope",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    canonical_key = Column(String(120), nullable=False, index=True)
    category = Column(String(60), nullable=False, index=True)
    sensitivity = Column(String(30), nullable=False, default="standard", index=True)
    mode = Column(String(30), nullable=False, default=AnswerPolicyMode.ask_each_time.value)
    encrypted_value = Column(Text)
    encrypted_label = Column(Text)
    encrypted_fallbacks = Column(Text)
    match_phrases = Column(JSON, default=list)
    scope = Column(String(30), nullable=False, default=AnswerPolicyScope.global_scope.value, index=True)
    scope_value = Column(String(255), nullable=False, default="")
    allow_autofill = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    confirmed_at = Column(DateTime(timezone=True))
    provenance = Column(
        String(40),
        nullable=False,
        default=AnswerPolicyProvenance.user_provided.value,
        index=True,
    )
    confidence = Column(Float, nullable=False, default=1.0)
    consent_metadata = Column(JSON, default=dict)
    source_metadata = Column(JSON, default=dict)
    expires_at = Column(DateTime(timezone=True), index=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="answer_policies")
