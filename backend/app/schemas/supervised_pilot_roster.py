from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


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
