#!/usr/bin/env python3
"""Build exact-head evidence for the Day 35 Phase 5 operations rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.services.day35_operations_rehearsal import (
    PILOT_CONFIGURATION_PATH,
    build_day35_rehearsal_gate,
)
from app.services.dead_letter_drill import run_dead_letter_recovery_drill


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SOURCES = (
    "backend/app/services/day35_operations_rehearsal.py",
    "backend/evidence/day35-unattended-pilot-configuration.json",
    "backend/app/services/autonomy_release_contract.py",
    "backend/app/services/phase4_candidate_gate.py",
    "backend/app/services/day33_recovery_chaos.py",
    "backend/app/services/dead_letter.py",
    "backend/app/services/dead_letter_drill.py",
    "backend/app/services/operations_policy.py",
    "backend/app/services/operational_observability.py",
    "backend/tests/test_day35_operations_rehearsal.py",
    "backend/tests/test_autonomy_release_contract.py",
    "backend/tests/test_phase4_candidate_gate.py",
    "backend/tests/test_day33_recovery_chaos.py",
    "backend/tests/test_dead_letter_drill.py",
    ".github/workflows/day35-operations-rehearsal-gate.yml",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_gate(verification_commit: str) -> dict:
    payload = build_day35_rehearsal_gate(
        verification_commit=verification_commit,
        root=REPO_ROOT,
    )

    # Keep simulated scheduling/policy behavior separate from a genuinely executed
    # checkpoint/dead-letter contract. The drill uses the production dead-letter
    # service in an isolated in-memory database and grants no consequential authority.
    dead_letter = run_dead_letter_recovery_drill()
    payload["executed_dead_letter_recovery"] = dead_letter
    payload["evidence_scope"] = {
        "scheduling_caps_quiet_hours_retries_alerts": "deterministic_no_submit_simulation",
        "crash_recovery": "executed_day33_recovery_contract",
        "checkpoint_dead_letter_recovery": "executed_production_dead_letter_contract",
        "external_network_or_browser": "not_exercised_day35",
    }
    payload["source_digests_sha256"] = {
        source: _sha256(REPO_ROOT / source)
        for source in SOURCES
    }
    payload["pilot_configuration_file_sha256"] = _sha256(
        REPO_ROOT / PILOT_CONFIGURATION_PATH
    )
    payload["gate_passed"] = bool(
        payload.get("gate_passed") is True
        and dead_letter.get("passed") is True
        and dead_letter.get("safety", {}).get("final_submit_clicked") is False
        and dead_letter.get("safety", {}).get("network_contacted") is False
        and dead_letter.get("safety", {}).get("submission_authorized") is False
        and dead_letter.get("safety", {}).get("outreach_authorized") is False
        and len(payload["source_digests_sha256"]) == len(SOURCES)
        and payload["pilot_configuration_freeze"]["valid"] is True
        and payload["provisional_autonomy_recommendation"]["eligible_to_enter_shadow_runs"] is True
        and payload["provisional_autonomy_recommendation"]["certified_autonomous_recommended"] is False
        and payload["provisional_autonomy_recommendation"]["promotion_authorized"] is False
        and payload["provisional_autonomy_recommendation"]["live_submission_authorized"] is False
        and payload["provisional_autonomy_recommendation"]["day39_promotion_blocked"] is True
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_gate(args.verification_commit.strip().lower())
    Path(args.output).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not payload["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
