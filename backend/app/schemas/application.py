from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.application import ApplicationStatus
from app.schemas.job import JobOut


class ApplicationCreate(BaseModel):
    job_id: int
    cover_letter: Optional[str] = None
    notes: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=255)


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


class ManualReviewResolve(BaseModel):
    resolution_notes: Optional[str] = None


class ManualReviewTaskOut(BaseModel):
    id: int
    application_id: int
    reason_code: str
    status: str
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)
    blocking_url: Optional[str]
    screenshot_path: Optional[str]
    resume_token: Optional[str]
    expires_at: Optional[datetime]
    resolved_at: Optional[datetime]
    resolution_notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class SubmissionEvidenceOut(BaseModel):
    id: int
    application_id: int
    evidence_type: str
    is_sufficient: bool
    final_url: Optional[str]
    confirmation_text: Optional[str]
    selector: Optional[str]
    external_application_id: Optional[str]
    screenshot_path: Optional[str]
    html_snapshot_path: Optional[str]
    payload_hash: Optional[str]
    evidence_metadata: Dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime

    class Config:
        from_attributes = True


class ApplicationEventOut(BaseModel):
    id: int
    application_id: int
    event_type: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class ApplicationOut(BaseModel):
    id: int
    user_id: int
    job_id: int
    job: Optional[JobOut]
    status: ApplicationStatus
    automation_state: str = "preparing"
    submission_idempotency_key: Optional[str]
    submission_attempt_count: int = 0
    last_submission_attempt_at: Optional[datetime]
    cover_letter: Optional[str]
    notes: Optional[str]
    applied_at: Optional[datetime]
    interview_at: Optional[datetime]
    offer_received_at: Optional[datetime]
    salary_offered: Optional[int]
    rejection_reason: Optional[str]
    followups: List[FollowUpOut] = Field(default_factory=list)
    manual_reviews: List[ManualReviewTaskOut] = Field(default_factory=list)
    submission_evidence: List[SubmissionEvidenceOut] = Field(default_factory=list)
    events: List[ApplicationEventOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
