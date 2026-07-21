from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SubmissionEvidenceReviewCreate(BaseModel):
    decision: str
    confirm_employer: str = Field(min_length=1, max_length=500)
    confirm_role: str = Field(min_length=1, max_length=500)
    confirm_evidence_type: str = Field(min_length=1, max_length=80)
    confirm_evidence_matches_application: bool
    review_acknowledgement: str = Field(min_length=1, max_length=32)
    notes: Optional[str] = Field(default=None, max_length=4000)


class SubmissionEvidenceReviewOut(BaseModel):
    id: int
    reference: str
    application_id: int
    evidence_id: int
    reviewer_user_id: int
    approval_reference: Optional[str]
    decision: str
    evidence_snapshot_hash: str
    application_payload_hash: Optional[str]
    review_notes: Optional[str]
    review_metadata: Dict[str, Any] = Field(default_factory=dict)
    reviewed_at: Optional[datetime]
    valid_for_current_evidence: bool = True


class SubmissionEvidenceReviewPreflightOut(BaseModel):
    ready_for_acceptance: bool
    blockers: List[str] = Field(default_factory=list)
    application_id: int
    application_state: str
    employer: str
    role: str
    application_url: str
    submission_idempotency_key: Optional[str]
    evidence: Dict[str, Any]
    approval_reference: Optional[str]
    application_payload_hash: Optional[str]
    platform: Optional[str] = None
    evidence_platform: Optional[str] = None
    evidence_adapter: Optional[str] = None
    target_identity_hash: Optional[str] = None
    target_verification: Dict[str, Any] = Field(default_factory=dict)
    existing_review: Optional[Dict[str, Any]] = None
