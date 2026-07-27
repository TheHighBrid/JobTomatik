import json
from datetime import datetime

import pytest

from app.services.lever_pilot_ingestion import (
    LeverPilotIngestionError,
    load_ledger,
    read_lever_pilot_readiness,
)


def _dry_run_record() -> dict:
    posting_id = "11111111-2222-3333-4444-555555555555"
    url = f"https://jobs.lever.co/planted-dry/{posting_id}/apply"
    return {
        "schema_version": "1.0",
        "run_id": "lv-planted-runtime-dry-run",
        "mode": "dry_run",
        "platform": "lever",
        "completed_at": datetime.utcnow().isoformat(),
        "employer": "Planted Runtime Employer",
        "role": "Analyst",
        "site": "planted-dry",
        "posting_id": posting_id,
        "region": "global",
        "board_token": "planted-dry",
        "job_id": posting_id,
        "application_url": url,
        "canonical_application_url": url,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "operator": "github-actions:TheHighBrid",
        "source_reference": "actions-run:planted:artifact:dry",
        "artifact_sha256": "a" * 64,
        "approval_reference": None,
        "controls_discovered": 3,
        "controls_filled": 3,
        "controls_skipped": 0,
        "controls_blocked": 0,
        "policies_used": 2,
        "uploads_verified": 1,
        "validation_errors": [],
        "handoff_reason": None,
        "handoff_boundary": None,
        "pre_submit_state": "ready_to_submit",
        "final_url": url,
        "final_submit_clicked": False,
        "confirmation_evidence_type": None,
        "confirmation_evidence_reference": None,
        "final_status": "dry_run_passed",
        "duplicate_guard_verified": None,
        "duplicate_submission_detected": False,
        "reviewed_by": None,
        "review_reference": None,
        "qualifies_for_dry_run_matrix": True,
        "synthetic_profile": True,
        "error": None,
        "notes": None,
    }


def test_core_runtime_loader_rejects_phase_a_record(tmp_path):
    ledger = tmp_path / "lever-pilot-ledger.jsonl"
    ledger.write_text(json.dumps(_dry_run_record()) + "\n", encoding="utf-8")

    with pytest.raises(LeverPilotIngestionError, match="Phase B records only"):
        load_ledger(ledger)


def test_core_readiness_cannot_use_runtime_dry_run_as_missing_baseline(tmp_path):
    ledger = tmp_path / "lever-pilot-ledger.jsonl"
    ledger.write_text(json.dumps(_dry_run_record()) + "\n", encoding="utf-8")

    with pytest.raises(LeverPilotIngestionError, match="Phase B records only"):
        read_lever_pilot_readiness(
            baseline_path=tmp_path / "missing-phase-a.csv",
            ledger_path=ledger,
        )
