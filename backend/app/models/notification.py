from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class NotificationType(str, enum.Enum):
    new_match = "new_match"
    status_change = "status_change"
    interview_request = "interview_request"
    offer_received = "offer_received"
    rejection = "rejection"
    followup_sent = "followup_sent"
    application_submitted = "application_submitted"
    system = "system"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(Enum(NotificationType), nullable=False)
    title = Column(String(500), nullable=False)
    message = Column(Text)
    data = Column(JSON, default={})
    read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")
