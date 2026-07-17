from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SupervisedApprovalCreate(BaseModel):
    confirm_employer: str = Field(min_length=1, max_length=500)
    confirm_role: str = Field(min_length=1, max_length=500)
    confirm_application_url: str = Field(min_length=1, max_length=1500)
    confirm_final_submit: bool
    expires_in_minutes: Optional[int] = Field(default=None, ge=1, le=60)
    notes: Optional[str] = Field(default=None, max_length=2000)


class SupervisedApprovalRevoke(BaseModel):
    reason: str = Field(default="revoked_by_user", min_length=1, max_length=200)


class SupervisedApprovalOut(BaseModel):
    reference: str
    application_id: int
    user_id: int
    platform: str
    status: str
    employer: str
    role: str
    application_url: str
    submission_idempotency_key: str
    profile_snapshot_hash: str
    resume_hash: str
    cover_letter_hash: str
    answer_payload_hash: str
    combined_payload_hash: str
    approved_at: datetime
    expires_at: datetime
    consumed_at: Optional[datetime]
    revoked_at: Optional[datetime]
    notes: Optional[str]
    approval_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime]


class SupervisedPreflightOut(BaseModel):
    ready: bool
    blockers: List[str] = Field(default_factory=list)
    application_id: int
    platform: str
    employer: str
    role: str
    application_url: str
    automation_state: str
    unresolved_manual_review_count: int
    global_live_submit_enabled: bool
    platform_pilot_enabled: bool
    submission_idempotency_key: str
    profile_snapshot_hash: str
    resume_hash: Optional[str]
    cover_letter_hash: str
    answer_payload_hash: str
    combined_payload_hash: str
    policy_count: int
    cover_letter_present: bool
    resume_filename: Optional[str]


class SupervisedSubmitQueued(BaseModel):
    task_id: str
    status: str
    application_id: int
    approval_reference: str
    idempotency_key: str
    dry_run: bool = False
