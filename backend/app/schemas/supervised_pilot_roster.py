from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SupervisedPilotCandidateImportIn(BaseModel):
    employer: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=500)
    application_url: str = Field(min_length=12, max_length=1000)
    location: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=5000)
    source_reference: Optional[str] = Field(default=None, max_length=500)


class SupervisedPilotCandidateImportOut(BaseModel):
    application_id: int
    job_id: int
    created_job: bool
    created_application: bool
    employer: str
    role: str
    application_url: str
    automation_state: str
    selection_policy: str
    submission_queued: bool = False
    approval_issued: bool = False
    runtime_flags_changed: bool = False


class LeverPhaseBLaunchSelectionReceipt(BaseModel):
    path: str
    sha256: str
    receipt_id: str


class LeverPhaseBLaunchCandidate(BaseModel):
    application_id: str
    review_id: str
    employer: str
    role: str
    location: Optional[str] = None
    application_url: str
    site: str
    posting_id: str
    region: str
    selection_reference: str
    selection_receipt_sha256: str
    dossier_artifact_path: str
    dossier_artifact_sha256: str
    dossier_sha256: str
    source_report_path: str
    source_report_sha256: str
    synthetic_preview: bool = True
    read_only: bool = True
    one_time_approval_required: bool = True
    materialized: bool = False
    job_id: Optional[int] = None
    materialized_application_id: Optional[int] = None
    automation_state: Optional[str] = None
    preparation_stage: str = "not_materialized"
    preparation_blockers: List[str] = Field(default_factory=list)
    preparation_next_action: str = "materialize"
    resume_present: bool = False
    application_cover_letter_present: bool = False
    application_cover_letter_matches_latest: bool = False
    official_posting_context_present: bool = False
    official_posting_sha256: Optional[str] = None
    cover_letter_material_id: Optional[int] = None
    cover_letter_material_status: Optional[str] = None
    cover_letter_material_version: Optional[int] = None
    cover_letter_review_status: Optional[str] = None
    resume_summary_material_id: Optional[int] = None
    resume_summary_material_status: Optional[str] = None
    resume_summary_material_version: Optional[int] = None
    resume_summary_review_status: Optional[str] = None
    material_review_eligible: bool = False
    open_review_count: int = 0
    active_approval_reference: Optional[str] = None
    active_approval_expires_at: Optional[datetime] = None
    latest_attempt_reference: Optional[str] = None
    latest_attempt_status: Optional[str] = None
    submission_queued: bool = False
    approval_issued: bool = False
    runtime_flags_changed: bool = False


class LeverPhaseBLaunchOut(BaseModel):
    schema_version: str
    selection_receipt: LeverPhaseBLaunchSelectionReceipt
    candidate_count: int
    materialized_count: int
    preparation_only: bool = True
    preparation_stage_counts: Dict[str, int] = Field(default_factory=dict)
    candidates: List[LeverPhaseBLaunchCandidate] = Field(default_factory=list)


class LeverPhaseBMaterializeOut(BaseModel):
    review_id: str
    launch_application_id: str
    application_id: int
    job_id: int
    created_job: bool
    created_application: bool
    employer: str
    role: str
    application_url: str
    automation_state: str
    selection_policy: str
    synthetic_preview: bool = True
    requires_fresh_runtime_preflight: bool = True
    submission_queued: bool = False
    approval_issued: bool = False
    runtime_flags_changed: bool = False


class LeverPhaseBPreparedMaterial(BaseModel):
    id: int
    material_type: str
    version: int
    status: str
    warning_count: int = 0
    review_status: str = "pending"


class LeverPhaseBPrepareMaterialsOut(BaseModel):
    review_id: str
    launch_application_id: str
    application_id: int
    job_id: int
    posting_sha256: str
    posting_source: str
    resume_filename: str
    resume_evidence_count: int
    evidence_unit_count: int
    evidence_digest: str
    evidence_rebuild: Dict[str, Any] = Field(default_factory=dict)
    review_eligible: bool
    critical_errors: List[str] = Field(default_factory=list)
    materials: List[LeverPhaseBPreparedMaterial] = Field(default_factory=list)
    automation_state: str
    requires_explicit_material_review: bool = True
    requires_fresh_runtime_preflight: bool = True
    approval_issued: bool = False
    submission_queued: bool = False


class LeverPhaseBMaterialReviewIn(BaseModel):
    approved: bool
    notes: Optional[str] = Field(default=None, max_length=5000)


class LeverPhaseBMaterialReviewOut(BaseModel):
    review_id: str
    application_id: int
    approved: bool
    material_review_status: str
    ready_for_fresh_preflight: bool
    automation_state: str
    open_review_count: int
    posting_sha256: Optional[str] = None
    evidence_digest: Optional[str] = None
    requires_fresh_runtime_preflight: bool = True
    approval_issued: bool = False
    submission_queued: bool = False


class SupervisedPilotPhaseA(BaseModel):
    qualifying_dry_run_count: int = 0
    distinct_employer_count: int = 0
    complete: bool = False


class SupervisedPilotPhaseB(BaseModel):
    confirmed_count: int = 0
    target: int = 10
    remaining: int = 10
    complete: bool = False


class SupervisedPilotExecutionFlags(BaseModel):
    global_live_submit_enabled: bool = False
    greenhouse_supervised_pilot_enabled: bool = False


class SupervisedPilotRosterCandidate(BaseModel):
    application_id: int
    job_id: int
    employer: str
    role: str
    application_url: str
    automation_state: str
    roster_status: str
    technical_ready: bool
    technical_blockers: List[str] = Field(default_factory=list)
    execution_ready: bool
    execution_blockers: List[str] = Field(default_factory=list)
    unresolved_manual_review_count: int = 0
    cover_letter_present: bool = False
    resume_filename: Optional[str] = None
    policy_count: int = 0
    active_approval_reference: Optional[str] = None
    active_approval_expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    already_confirmed: bool = False
    already_ingested: bool = False


class SupervisedPilotRosterOut(BaseModel):
    selection_policy: str
    ordering: str
    phase_a: SupervisedPilotPhaseA
    phase_b: SupervisedPilotPhaseB
    execution_flags: SupervisedPilotExecutionFlags
    candidate_count: int
    technically_ready_count: int
    candidates: List[SupervisedPilotRosterCandidate] = Field(default_factory=list)
    readiness_available: bool
