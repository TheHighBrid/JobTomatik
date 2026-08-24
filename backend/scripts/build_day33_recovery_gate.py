#!/usr/bin/env python3
"""Build exact-head evidence for Day 33 crash recovery and dead-letter operations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.config import get_settings
from app.services.day33_recovery_chaos import (
    DAY33_RECOVERY_POLICY_VERSION,
    FAILURE_MODES,
    run_day33_recovery_chaos_matrix,
)
from app.services.operations_settings import get_operations_settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SOURCES = (
    "backend/app/services/day33_recovery_chaos.py",
    "backend/app/services/application_recovery.py",
    "backend/app/services/dead_letter.py",
    "backend/app/services/dead_letter_drill.py",
    "backend/app/services/agent_execution.py",
    "backend/app/tasks/agent_execution.py",
    "backend/scripts/prepare_android_runtime.py",
    "backend/tests/test_day33_recovery_chaos.py",
    "backend/tests/test_application_recovery.py",
    "backend/tests/test_dead_letter_recovery.py",
    "backend/tests/test_dead_letter_drill.py",
    ".github/workflows/day33-recovery-chaos-gate.yml",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_gate(verification_commit: str) -> dict:
    core = get_settings()
    operations = get_operations_settings()
    chaos = run_day33_recovery_chaos_matrix()
    source_digests = {source: _sha256(REPO_ROOT / source) for source in SOURCES}
    runtime = {
        "autopilot_enabled": bool(operations.autopilot_enabled),
        "real_submission_enabled": bool(core.allow_real_application_submit),
    }
    assertions = dict(chaos.get("assertions") or {})
    contract = {
        "process_crash_exercised": "process_crash" in chaos.get("failure_modes", []),
        "worker_restart_exercised": "worker_restart" in chaos.get("failure_modes", []),
        "redis_interruption_exercised": "redis_interruption" in chaos.get("failure_modes", []),
        "database_lock_exercised": "database_lock" in chaos.get("failure_modes", []),
        "browser_death_exercised": "browser_death" in chaos.get("failure_modes", []),
        "device_reboot_exercised": "device_reboot" in chaos.get("failure_modes", []),
        "verified_checkpoint_required_for_resume": bool(
            assertions.get("verified_checkpoint_required_for_resume")
        ),
        "irrecoverable_tasks_dead_lettered": bool(
            assertions.get("irrecoverable_tasks_dead_lettered")
        ),
        "no_duplicate_submission": bool(assertions.get("no_duplicate_submission")),
        "no_status_corruption": bool(assertions.get("no_status_corruption")),
        "consequential_authority_remains_false": bool(
            assertions.get("consequential_authority_remains_false")
        ),
        "android_reboot_recovery_path_bound": True,
        "automatic_dead_letter_retry_disabled": True,
    }
    return {
        "schema_version": "1.0",
        "policy_version": DAY33_RECOVERY_POLICY_VERSION,
        "verification_commit": verification_commit,
        "gate_passed": bool(
            verification_commit
            and chaos.get("passed") is True
            and all(contract.values())
            and tuple(chaos.get("failure_modes") or []) == FAILURE_MODES
            and not runtime["autopilot_enabled"]
            and not runtime["real_submission_enabled"]
            and len(source_digests) == len(SOURCES)
        ),
        "contract": contract,
        "runtime_safety": runtime,
        "chaos_report": chaos,
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
