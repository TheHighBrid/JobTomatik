from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.application import ApplicationStatus
from app.schemas.job import JobOut


class ApplicationCreate(BaseModel):
    job_id: int
    cover_letter: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatus] = None
    notes: Optional[str] = None
    interview_at: Optional[datetime] = None
    salary_offered: Optional[int] = None
    rejection_reason: Optional[str] = None


class FollowUpCreate(BaseModel):
    scheduled_at: datetime
    subject: str
    message: Optional[str] = None
    recipient_email: str


class FollowUpOut(BaseModel):
    id: int
    application_id: int
    scheduled_at: datetime
    sent_at: Optional[datetime]
    subject: Optional[str]
    message: Optional[str]
    recipient_email: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ApplicationOut(BaseModel):
    id: int
    user_id: int
    job_id: int
    job: Optional[JobOut]
    status: ApplicationStatus
    cover_letter: Optional[str]
    notes: Optional[str]
    applied_at: Optional[datetime]
    interview_at: Optional[datetime]
    offer_received_at: Optional[datetime]
    salary_offered: Optional[int]
    rejection_reason: Optional[str]
    followups: Optional[List[FollowUpOut]] = []
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
