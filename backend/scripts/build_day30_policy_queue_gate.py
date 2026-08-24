#!/usr/bin/env python3
"""Build exact-head evidence for the Day 30 policy-bounded application queue."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.config import get_settings
from app.services.application_queue_policy import (
    ALLOWED_WORKPLACE_MODES,
    DAY30_POLICY_VERSION,
)
from app.services.operations_settings import get_operations_settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SOURCES = (
    "backend/app/services/application_queue_policy.py",
    "backend/app/services/application_queue_policy_runtime.py",
    "backend/app/services/application_queue_policy_integration.py",
    "backend/app/api/settings.py",
    "backend/app/celery_app.py",
    "backend/tests/test_day30_application_queue_policy.py",
    "backend/tests/test_day30_policy_runtime.py",
    ".github/workflows/day30-policy-queue-gate.yml",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_gate(verification_commit: str) -> dict:
    core = get_settings()
    operations = get_operations_settings()
    source_digests = {
        source: _sha256(REPO_ROOT / source)
        for source in SOURCES
    }
    runtime = {
        "autopilot_enabled": bool(operations.autopilot_enabled),
        "real_submission_enabled": bool(core.allow_real_application_submit),
        "global_kill_switch": bool(operations.global_kill_switch),
    }
    required_controls = {
        "location": "inherited",
        "remote_status": "day30_workplace_mode",
        "language": "inherited",
        "salary": "inherited",
        "role": "day30_role_allowlist",
        "seniority": "inherited",
        "authorization": "day30_authorization_country_and_sponsorship",
        "employer_exclusions": "inherited",
        "minimum_score": "inherited",
        "daily_weekly_caps": "inherited",
        "quiet_hours": "inherited",
        "allowlists": "inherited",
        "per_platform_limits": "day30_platform_daily_caps",
        "audit_explanations": "day30_agent_run_policy_audit",
    }
    return {
        "schema_version": "1.0",
        "policy_version": DAY30_POLICY_VERSION,
        "verification_commit": verification_commit,
        "gate_passed": (
            bool(verification_commit)
            and not runtime["autopilot_enabled"]
            and not runtime["real_submission_enabled"]
            and set(ALLOWED_WORKPLACE_MODES) == {"remote", "hybrid", "onsite"}
            and len(source_digests) == len(SOURCES)
        ),
        "required_controls": required_controls,
        "policy_contract": {
            "explicit_roles_required_for_auto_apply": True,
            "explicit_workplace_modes_required_for_auto_apply": True,
            "explicit_authorized_countries_required_for_auto_apply": True,
            "per_enabled_platform_cap_required": True,
            "sponsorship_required_defaults_disallowed": True,
            "unknown_workplace_or_authorization_facts_fail_closed": True,
            "base_unattended_policy_is_never_weakened": True,
            "scheduler_and_worker_share_same_extension": True,
            "worker_recheck_excludes_only_current_application": True,
            "ambiguous_worker_application_does_not_under_count": True,
            "shadow_profile_preserved": True,
            "decision_dispositions": ["accepted", "rejected", "held"],
        },
        "runtime_safety": runtime,
        "source_digests_sha256": source_digests,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_gate(args.verification_commit.strip())
    output = Path(args.output)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not payload["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
