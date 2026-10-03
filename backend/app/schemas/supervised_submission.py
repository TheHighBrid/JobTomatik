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


class OperatorAssistedApprovalCreate(BaseModel):
    handoff_public_id: str = Field(min_length=1, max_length=64)
    confirm_employer: str = Field(min_length=1, max_length=500)
    confirm_role: str = Field(min_length=1, max_length=500)
    confirm_application_url: str = Field(min_length=1, max_length=1500)
    confirm_operator_final_click: bool
    expires_in_minutes: Optional[int] = Field(default=None, ge=1, le=60)
    notes: Optional[str] = Field(default=None, max_length=2000)


class OperatorAssistedFinalSubmitRequest(BaseModel):
    lease_token: str = Field(min_length=24, max_length=512)


class OperatorAssistedFinalSubmitOut(BaseModel):
    application_id: int
    handoff_public_id: str
    approval_reference: str
    action: str = "operator_submit"
    current_url: str
    submission_confirmed: bool = False
    final_action_started: bool = True
    automatic_retry_allowed: bool = False


class OperatorAssistedPreflightOut(BaseModel):
    ready: bool
    blockers: List[str] = Field(default_factory=list)
    application_id: int
    platform: str
    platform_display_name: Optional[str] = None
    adapter_version: Optional[str] = None
    employer: str
    role: str
    application_url: str
    original_application_url: Optional[str] = None
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
    target_identity: Dict[str, Any] = Field(default_factory=dict)
    target_identity_hash: Optional[str] = None
    target_identity_verified: bool = False
    target_liveness: Dict[str, Any] = Field(default_factory=dict)
    form_schema_hash: Optional[str] = None
    form_schema: Dict[str, Any] = Field(default_factory=dict)
    submission_mode: str
    operator_final_click_required: bool
    automated_submission_authorized: bool
    queue_submission_authorized: bool
    autopilot_enabled: bool
    operator_final_submit_boundary: bool = False
    operator_handoff_public_id: Optional[str] = None


class OperatorAssistedPrepareOut(BaseModel):
    application_id: int
    status: str
    task_id: Optional[str] = None
    submission_mode: str = "operator_assisted_prepare"
    handoff_public_id: Optional[str] = None
    automated_submission_authorized: bool = False
    final_submit_clicked_by_jobtomatik: bool = False


class OperatorAssistedAuthorizationOut(BaseModel):
    application_id: int
    approval_reference: str
    handoff_public_id: str
    status: str
    application_url: str
    combined_payload_hash: str
    attempt_number: int
    operator_final_click_required: bool = True
    automated_submission_authorized: bool = False
    worker_task_created: bool = False
    queue_created: bool = False


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
    platform_display_name: Optional[str] = None
    adapter_version: Optional[str] = None
    employer: str
    role: str
    application_url: str
    original_application_url: Optional[str] = None
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
    target_identity: Dict[str, Any] = Field(default_factory=dict)
    target_identity_hash: Optional[str] = None
    target_identity_verified: bool = False
    target_liveness: Dict[str, Any] = Field(default_factory=dict)
    form_schema_hash: Optional[str] = None
    form_schema: Dict[str, Any] = Field(default_factory=dict)


class SupervisedSubmitQueued(BaseModel):
    task_id: str
    status: str
    application_id: int
    approval_reference: str
    attempt_reference: str
    attempt_number: int
    idempotency_key: str
    idempotent: bool = False
    duplicate_final_action_prevented: bool = False
    dry_run: bool = False
