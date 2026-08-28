from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CurrentLeverPhaseBImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employer: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=500)
    application_url: str = Field(min_length=12, max_length=1000)
    location: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=5000)
    source_reference: Optional[str] = Field(default=None, max_length=500)


class CurrentLeverPhaseBImportOut(BaseModel):
    application_id: int
    job_id: int
    created_job: bool
    created_application: bool
    employer: str
    role: str
    application_url: str
    automation_state: str
    selection_policy: str
    target_identity_verified: bool
    site: str
    posting_id: str
    region: str
    adapter_version: str
    submission_queued: bool = False
    approval_issued: bool = False
    runtime_flags_changed: bool = False
