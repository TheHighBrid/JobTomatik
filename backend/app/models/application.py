from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, Enum, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    applying = "applying"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.pending)
    cover_letter = Column(Text)
    resume_path = Column(String(500))
    notes = Column(Text)
    applied_at = Column(DateTime(timezone=True))
    interview_at = Column(DateTime(timezone=True))
    offer_received_at = Column(DateTime(timezone=True))
    salary_offered = Column(Integer)
    rejection_reason = Column(Text)
    automation_log = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="applications")
    job = relationship("Job", back_populates="applications")
    followups = relationship("FollowUp", back_populates="application", cascade="all, delete-orphan")


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
