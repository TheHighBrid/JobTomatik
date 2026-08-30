from __future__ import annotations

from typing import Dict, Optional

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


class CurrentLeverPhaseBMaterialReviewIn(BaseModel):
    """Explicit owner decision for the exact current Lever material bundle shown.

    Approval remains intentionally fail-closed. The UI must submit the exact
    application-bound acknowledgment plus the displayed material IDs, versions,
    posting digest, and evidence digest. A generic approve boolean is not sufficient
    authority, and a stale tab cannot silently approve a newer bundle.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool
    notes: Optional[str] = Field(default=None, max_length=5000)
    acknowledgment: Optional[str] = Field(default=None, max_length=200)
    material_ids: Optional[Dict[str, int]] = None
    material_versions: Optional[Dict[str, int]] = None
    posting_sha256: Optional[str] = Field(default=None, max_length=64)
    evidence_digest: Optional[str] = Field(default=None, max_length=64)
