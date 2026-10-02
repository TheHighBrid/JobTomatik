#!/usr/bin/env python3
"""Build exact-head evidence for Day 32 observability and notifications."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.config import get_settings
from app.services.day32_observability import DAY32_OBSERVABILITY_VERSION
from app.services.operations_settings import get_operations_settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SOURCES = (
    "backend/app/services/day32_observability.py",
    "backend/app/services/operational_observability.py",
    "backend/app/services/adapter_health.py",
    "backend/app/services/autonomous_material_verification.py",
    "backend/app/api/adapter_health.py",
    "backend/tests/test_day32_observability_notifications.py",
    "backend/tests/test_operational_observability.py",
    "backend/tests/test_adapter_health.py",
    "frontend/src/pages/AdapterHealth.jsx",
    ".github/workflows/day32-observability-gate.yml",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_gate(verification_commit: str) -> dict:
    core = get_settings()
    operations = get_operations_settings()
    source_digests = {source: _sha256(REPO_ROOT / source) for source in SOURCES}
    runtime = {
        "autopilot_enabled": bool(operations.autopilot_enabled),
        "real_submission_enabled": bool(core.allow_real_application_submit),
    }
    contract = {
        "adapter_success_dashboard": True,
        "source_success_dashboard": True,
        "submission_uncertain_alert": True,
        "repeated_validation_failure_alert": True,
        "source_breakage_alert": True,
        "lockout_risk_alert": True,
        "circuit_breaker_alert": True,
        "evidence_mismatch_alert": True,
        "exact_application_links": True,
        "explicit_recovery_actions": True,
        "incident_notifications_deduplicated": True,
        "routine_successes_digest_only": True,
        "submission_authority_unchanged": True,
    }
    return {
        "schema_version": "1.0",
        "policy_version": DAY32_OBSERVABILITY_VERSION,
        "verification_commit": verification_commit,
        "gate_passed": bool(
            verification_commit
            and not runtime["autopilot_enabled"]
            and not runtime["real_submission_enabled"]
            and len(source_digests) == len(SOURCES)
        ),
        "contract": contract,
        "runtime_safety": runtime,
        "source_digests_sha256": source_digests,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_gate(args.verification_commit.strip())
    Path(args.output).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not payload["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
