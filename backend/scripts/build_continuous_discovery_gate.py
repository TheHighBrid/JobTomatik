#!/usr/bin/env python3
"""Build exact-head evidence for the Day 29 continuous discovery gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from app.celery_app import celery_app
from app.config import get_settings
from app.services.discovery_scheduler import (
    DISCOVERY_FRESHNESS_TTL_HOURS,
    DISCOVERY_POLICY_VERSION,
    SOURCE_BACKOFF_BASE_SECONDS,
    SOURCE_BACKOFF_MAX_SECONDS,
)
from app.services.operations_settings import get_operations_settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
BOUND_FILES = (
    "backend/app/celery_app.py",
    "backend/app/tasks/discovery.py",
    "backend/app/services/discovery_scheduler.py",
    "backend/app/services/discovery_freshness_integration.py",
    "backend/app/services/discovery_dedup.py",
    "backend/app/services/job_identity.py",
    "backend/tests/test_continuous_discovery.py",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_gate(verification_commit: str) -> dict:
    commit = str(verification_commit or "").strip().lower()
    if not SHA_RE.fullmatch(commit):
        raise ValueError("verification_commit must be an exact 40-character lowercase git SHA")

    core = get_settings()
    operations = get_operations_settings()
    beat = dict(celery_app.conf.beat_schedule or {})
    continuous = dict(beat.get("continuous-job-discovery-hourly") or {})
    task_routes = dict(celery_app.conf.task_routes or {})
    includes = list(celery_app.conf.include or [])

    invariants = {
        "continuous_discovery_task_registered": (
            continuous.get("task") == "app.tasks.discovery.run_continuous_discovery"
        ),
        "continuous_discovery_module_loaded": "app.tasks.discovery" in includes,
        "continuous_discovery_uses_scraping_queue": (
            dict(task_routes.get("app.tasks.discovery.*") or {}).get("queue") == "scraping"
        ),
        "application_autopilot_disabled_in_gate": operations.autopilot_enabled is False,
        "real_submission_disabled_in_gate": core.allow_real_application_submit is False,
        "source_backoff_is_bounded": (
            0 < SOURCE_BACKOFF_BASE_SECONDS <= SOURCE_BACKOFF_MAX_SECONDS <= 6 * 60 * 60
        ),
        "freshness_ttl_is_bounded": 0 < DISCOVERY_FRESHNESS_TTL_HOURS <= 72,
    }

    payload = {
        "schema": "day29_continuous_discovery_gate_v1",
        "verification_commit": commit,
        "policy_version": DISCOVERY_POLICY_VERSION,
        "scheduler": {
            "task": continuous.get("task"),
            "beat_key": "continuous-job-discovery-hourly",
            "cadence": "hourly_at_minute_12_utc",
            "queue": dict(task_routes.get("app.tasks.discovery.*") or {}).get("queue"),
            "autopilot_required_for_discovery": False,
            "global_kill_switch_preserved": True,
        },
        "source_backoff": {
            "base_seconds": SOURCE_BACKOFF_BASE_SECONDS,
            "max_seconds": SOURCE_BACKOFF_MAX_SECONDS,
            "success_resets_failure_streak": True,
            "retained_diagnostics_source": "AgentRun.result.source_diagnostics",
        },
        "freshness": {
            "ttl_hours": DISCOVERY_FRESHNESS_TTL_HOURS,
            "last_seen_field": "raw_data.discovery_last_seen_at",
            "first_seen_field": "raw_data.discovery_first_seen_at",
            "stale_discovered_candidates_fail_closed": True,
            "manual_jobs_without_discovery_provenance_exempt": True,
        },
        "dedup": {
            "provider_posting_ids": True,
            "canonical_board_urls": True,
            "proof_based_cross_source_employer_apply_url": True,
            "fuzzy_title_only_matching": False,
        },
        "runtime": {
            "autopilot_enabled": operations.autopilot_enabled,
            "real_submission_enabled": core.allow_real_application_submit,
        },
        "source_digests": {
            relative: _sha256(REPO_ROOT / relative) for relative in BOUND_FILES
        },
        "invariants": invariants,
        "gate_passed": all(invariants.values()),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_gate(args.verification_commit)
    output = Path(args.output)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not payload["gate_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
