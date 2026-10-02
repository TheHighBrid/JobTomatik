from __future__ import annotations

import copy
import json
from pathlib import Path

from app.services.autonomy_release_contract import (
    AUTONOMY_RELEASE_CONTRACT_VERSION,
    AUTONOMY_RELEASE_SCHEMA_VERSION,
    AUTONOMY_SIGNATURE_METHOD,
    REQUIRED_SHADOW_CHECKS,
    autonomy_release_contract_requirements,
    compute_autonomy_manifest_digest,
    compute_autonomy_manifest_signature,
    validate_autonomy_release_manifest,
)


SIGNING_KEY = "jobtomatik-day39-contract-test-key-000001"


def _resign(manifest: dict) -> dict:
    manifest["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(manifest)
    manifest["attestation"]["signature"] = compute_autonomy_manifest_signature(
        manifest,
        SIGNING_KEY,
    )
    return manifest


def _manifest() -> dict:
    commit = "a" * 40
    manifest = {
        "schema_version": AUTONOMY_RELEASE_SCHEMA_VERSION,
        "adapter": {"name": "lever", "version": "1.1.0"},
        "source": {
            "release_commit": commit,
            "fixture_digest": "sha256:" + "1" * 64,
            "evidence_digest": "sha256:" + "2" * 64,
            "policy_digest": "sha256:" + "3" * 64,
        },
        "reliability_window": {
            "evidence_type": "supervised_real_submission",
            "attempts": 10,
            "confirmed_successes": 10,
            "distinct_confirmed_submissions": 10,
            "independently_reviewed_successes": 10,
            "success_rate": 1.0,
            "false_positive_submitted_records": 0,
            "duplicate_submissions": 0,
            "uncertain_outcomes_credited_as_submitted": 0,
        },
        "retry_policy": {
            "bounded": True,
            "max_automatic_retries_per_attempt": 1,
            "no_retry_after_submit_click_without_confirmation": True,
        },
        "circuit_breaker": {
            "verified": True,
            "failure_threshold": 3,
            "halts_new_submissions": True,
        },
        "recovery_drills": {
            "process_crash": True,
            "worker_restart": True,
            "redis_interruption": True,
            "database_lock": True,
            "browser_death": True,
        },
        "policy_readiness": {
            "ready": True,
            "daily_weekly_caps": True,
            "quiet_hours": True,
            "employer_exclusions": True,
            "platform_limits": True,
            "kill_switch": True,
        },
        "shadow_runs": {name: True for name in REQUIRED_SHADOW_CHECKS},
        "approval": {
            "approved": True,
            "approval_reference": "owner-day39-contract-test",
            "approved_for_commit": commit,
        },
        "integrity": {"algorithm": "sha256", "manifest_digest": ""},
        "attestation": {
            "method": AUTONOMY_SIGNATURE_METHOD,
            "key_id": "day39-test-key",
            "signature": "",
        },
    }
    return _resign(manifest)


def _validate(manifest: dict) -> dict:
    return validate_autonomy_release_manifest(
        manifest,
        adapter_name="lever",
        adapter_version="1.1.0",
        trusted_signing_key=SIGNING_KEY,
    )


def test_day39_v2_contract_requires_truthful_rolling_24h_shadow_evidence():
    manifest = _manifest()
    result = _validate(manifest)

    assert result["passed"] is True
    assert AUTONOMY_RELEASE_SCHEMA_VERSION == "autonomy_release_v2"
    assert AUTONOMY_RELEASE_CONTRACT_VERSION == "day39_v2"
    assert "daily_cap_reset_verified" not in REQUIRED_SHADOW_CHECKS
    assert "production_policy_diagnostics_non_authoritative" in REQUIRED_SHADOW_CHECKS
    assert "rolling_24h_semantics_verified" in REQUIRED_SHADOW_CHECKS
    assert "rolling_24h_membership_rollover_verified" in REQUIRED_SHADOW_CHECKS

    requirements = autonomy_release_contract_requirements()
    assert requirements["capacity_semantics"] == "rolling_previous_24_hours"
    assert requirements["legacy_utc_midnight_daily_reset_claims_rejected"] is True


def test_legacy_v1_daily_reset_manifest_cannot_be_reinterpreted_as_v2():
    legacy = copy.deepcopy(_manifest())
    legacy["schema_version"] = "autonomy_release_v1"
    legacy["shadow_runs"].pop("production_policy_diagnostics_non_authoritative")
    legacy["shadow_runs"].pop("rolling_24h_semantics_verified")
    legacy["shadow_runs"].pop("rolling_24h_membership_rollover_verified")
    legacy["shadow_runs"]["daily_cap_reset_verified"] = True
    _resign(legacy)

    result = _validate(legacy)

    assert result["passed"] is False
    assert "schema_version" in result["missing"]
    assert "shadow_production_policy_diagnostics_non_authoritative" in result["missing"]
    assert "shadow_rolling_24h_semantics_verified" in result["missing"]
    assert "shadow_rolling_24h_membership_rollover_verified" in result["missing"]
    assert result["checks"].get("shadow_daily_cap_reset_verified") is None


def test_machine_schema_matches_v2_capacity_contract():
    schema_path = Path(__file__).parents[1] / "schemas" / "autonomy-release.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    shadow = schema["properties"]["shadow_runs"]

    assert schema["properties"]["schema_version"]["const"] == "autonomy_release_v2"
    assert "daily_cap_reset_verified" not in shadow["required"]
    assert "daily_cap_reset_verified" not in shadow["properties"]
    assert "production_policy_diagnostics_non_authoritative" in shadow["required"]
    assert "rolling_24h_semantics_verified" in shadow["required"]
    assert "rolling_24h_membership_rollover_verified" in shadow["required"]
    assert set(shadow["required"]) == set(REQUIRED_SHADOW_CHECKS)
