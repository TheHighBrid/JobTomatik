from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HandoffSessionOut(BaseModel):
    public_id: str
    application_id: int
    manual_review_id: int
    challenge_type: str
    status: str
    browser_provider: str
    browser_session_id: Optional[str]
    current_url: Optional[str]
    screenshot_path: Optional[str]
    resume_attempt_count: int
    max_resume_attempts: int
    expires_at: datetime
    lease_expires_at: Optional[datetime]
    claimed_at: Optional[datetime]
    ready_at: Optional[datetime]
    resumed_at: Optional[datetime]
    completed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    failure_reason: Optional[str]
    handoff_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class HandoffIssuedOut(BaseModel):
    session: HandoffSessionOut
    resume_token: str


class HandoffClaimRequest(BaseModel):
    resume_token: str = Field(min_length=24, max_length=512)


class HandoffClaimOut(BaseModel):
    session: HandoffSessionOut
    lease_token: str


class HandoffLeaseRequest(BaseModel):
    lease_token: str = Field(min_length=24, max_length=512)


class HandoffReadyRequest(HandoffLeaseRequest):
    provider_verification: Dict[str, Any] = Field(default_factory=dict)


class HandoffCancelRequest(BaseModel):
    reason: str = Field(default="Cancelled by user.", max_length=500)


class HandoffSessionEventOut(BaseModel):
    id: int
    handoff_session_id: int
    application_id: int
    event_type: str
    actor_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class HandoffDetailOut(HandoffSessionOut):
    events: List[HandoffSessionEventOut] = Field(default_factory=list)
