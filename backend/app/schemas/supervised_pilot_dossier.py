from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel


class SupervisedPilotDossierOut(BaseModel):
    snapshot_version: str
    scope: str
    selection_policy: str
    read_only: bool
    application_id: int
    target: Dict[str, Any]
    application_state: Dict[str, Any]
    exact_payload: Dict[str, Any]
    preflight: Dict[str, Any]
    kill_switches: Dict[str, Any]
    mandatory_handoff_boundaries: Dict[str, Any]
    manual_review_state: Dict[str, Any]
    approval_state: Dict[str, Any]
    submission_evidence_state: Dict[str, Any]
    independent_review_state: Dict[str, Any]
    audit_state: Dict[str, Any]
    pilot_progress: Dict[str, Any]
    dossier_sha256: str
    download_filename: str
