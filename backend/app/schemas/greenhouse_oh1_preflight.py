"""Response schema for the read-only GH-OH1 readiness report."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class GreenhouseOH1PreflightOut(BaseModel):
    """Represent the serialized GH-OH1 readiness result for an authenticated owner."""

    preflight_version: str
    status: str
    ready: bool
    application_id: int
    blockers: List[str] = Field(default_factory=list)
    target: Dict[str, Any] = Field(default_factory=dict)
    exact_payload: Dict[str, Any] = Field(default_factory=dict)
    dossier_sha256: str
    structural_preflight: Dict[str, Any] = Field(default_factory=dict)
    runtime_contract: Dict[str, Any] = Field(default_factory=dict)
    duplicate_defense: Dict[str, Any] = Field(default_factory=dict)
    approval_state: Dict[str, Any] = Field(default_factory=dict)
    safety_boundary: Dict[str, Any] = Field(default_factory=dict)
