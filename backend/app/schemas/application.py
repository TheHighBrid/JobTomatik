from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

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
    subject: str = Field(min_length=1, max_length=500)
    message: str = Field(min_length=1, max_length=10000)
    recipient_email: Optional[str] = Field(default=None, max_length=255)
    recruiter_contact_id: Optional[int] = Field(default=None, ge=1)


class FollowUpUpdate(BaseModel):
    scheduled_at: Optional[datetime] = None
    subject: Optional[str] = Field(default=None, min_length=1, max_length=500)
    message: Optional[str] = Field(default=None, min_length=1, max_length=10000)
    recipient_email: Optional[str] = Field(default=None, max_length=255)
    recruiter_contact_id: Optional[int] = Field(default=None, ge=1)


class FollowUpApprovalRequest(BaseModel):
    acknowledgment: str = Field(min_length=10, max_length=500)


class FollowUpRevokeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class FollowUpPreflightOut(BaseModel):
    followup_id: int
    application_id: Optional[int] = None
    status: str
    approval_status: str
    approval_reference: Optional[str] = None
    approval_active: bool
    approval_expires_at: Optional[str] = None
    eligible_for_approval: bool
    ready_for_delivery: bool
    blockers: List[str] = Field(default_factory=list)
    payload_hash: Optional[str] = None
    payload_drifted: bool
    recipient_email: Optional[str] = None
    recipient_hash: Optional[str] = None
    recruiter_contact_id: Optional[int] = None
    scheduled_at: Optional[str] = None
    due: bool
    provider_configured: bool
    global_send_enabled: bool
    expected_acknowledgment: str
    send_idempotency_key: Optional[str] = None
    send_attempt_count: int = 0
    last_send_attempt_at: Optional[str] = None
    sent_at: Optional[str] = None
    delivery_metadata: Dict[str, Any] = Field(default_factory=dict)


class FollowUpQueueOut(BaseModel):
    followup_id: int
    status: str
    task_id: Optional[str] = None
    queued: bool
    idempotent: bool = False
    duplicate_delivery_prevented: bool = False


class FollowUpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    recruiter_contact_id: Optional[int] = None
    scheduled_at: datetime
    sent_at: Optional[datetime]
    subject: Optional[str]
    message: Optional[str]
    recipient_email: Optional[str]
    status: str
    payload_hash: Optional[str] = None
    approval_reference: Optional[str] = None
    approval_status: str = "unapproved"
    approval_payload_hash: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_expires_at: Optional[datetime] = None
    approved_by_user_id: Optional[int] = None
    send_idempotency_key: Optional[str] = None
    send_attempt_count: int = 0
    last_send_attempt_at: Optional[datetime] = None
    delivery_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime] = None


class ManualReviewResolve(BaseModel):
    resolution_notes: Optional[str] = None


class ManualReviewTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class SubmissionEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class ApplicationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    event_type: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    job_id: int
    job: Optional[JobOut]
    status: ApplicationStatus
    automation_state: str = "preparing"
    source_listing_url: Optional[str] = None
    application_target_url: Optional[str] = None
    application_target_status: str = "unresolved"
    application_target_resolved_at: Optional[datetime] = None
    application_target_metadata: Optional[Dict[str, Any]] = None
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