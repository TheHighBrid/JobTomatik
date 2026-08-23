import copy
import json
from pathlib import Path

from app.services.autonomy_release_contract import (
    AUTONOMY_RELEASE_CONTRACT_VERSION,
    AUTONOMY_RELEASE_SCHEMA_VERSION,
    MIN_RELIABILITY_ATTEMPTS,
    MIN_SUCCESS_RATE,
    autonomy_release_contract_requirements,
    compute_autonomy_manifest_digest,
    validate_autonomy_release_manifest,
)


def valid_manifest(*, adapter_name="ashby", adapter_version="1.1.0", commit="a" * 40):
    manifest = {
        "schema_version": AUTONOMY_RELEASE_SCHEMA_VERSION,
        "adapter": {"name": adapter_name, "version": adapter_version},
        "source": {
            "release_commit": commit,
            "fixture_digest": "sha256:" + "1" * 64,
            "evidence_digest": "sha256:" + "2" * 64,
            "policy_digest": "sha256:" + "3" * 64,
        },
        "reliability_window": {
            "attempts": MIN_RELIABILITY_ATTEMPTS,
            "confirmed_successes": MIN_RELIABILITY_ATTEMPTS,
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
        "approval": {
            "approved": True,
            "approval_reference": "owner-day27-approval",
            "approved_for_commit": commit,
        },
        "integrity": {"algorithm": "sha256", "manifest_digest": ""},
    }
    manifest["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(manifest)
    return manifest


def test_valid_manifest_satisfies_day27_contract():
    manifest = valid_manifest()
    result = validate_autonomy_release_manifest(
        manifest,
        adapter_name="ashby",
        adapter_version="1.1.0",
    )

    assert result["passed"] is True
    assert result["missing"] == []
    assert result["manifest_digest"] == compute_autonomy_manifest_digest(manifest)
    assert result["requirements"]["contract_version"] == AUTONOMY_RELEASE_CONTRACT_VERSION
    assert result["requirements"]["minimum_success_rate"] == MIN_SUCCESS_RATE


def test_manifest_digest_detects_any_evidence_tampering():
    manifest = valid_manifest()
    tampered = copy.deepcopy(manifest)
    tampered["reliability_window"]["duplicate_submissions"] = 1

    result = validate_autonomy_release_manifest(
        tampered,
        adapter_name="ashby",
        adapter_version="1.1.0",
    )

    assert result["passed"] is False
    assert "zero_duplicate_submissions" in result["missing"]
    assert "manifest_digest_matches" in result["missing"]


def test_adapter_version_and_exact_commit_are_immutable_bindings():
    manifest = valid_manifest(commit="b" * 40)

    wrong_version = validate_autonomy_release_manifest(
        manifest,
        adapter_name="ashby",
        adapter_version="1.2.0",
    )
    assert wrong_version["passed"] is False
    assert "adapter_version" in wrong_version["missing"]

    wrong_commit = copy.deepcopy(manifest)
    wrong_commit["approval"]["approved_for_commit"] = "c" * 40
    wrong_commit["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(wrong_commit)
    result = validate_autonomy_release_manifest(
        wrong_commit,
        adapter_name="ashby",
        adapter_version="1.1.0",
    )
    assert result["passed"] is False
    assert "approval_exact_release_commit" in result["missing"]


def test_reliability_window_requires_sustained_consistent_success_rate():
    manifest = valid_manifest()
    manifest["reliability_window"].update(
        {
            "attempts": 20,
            "confirmed_successes": 19,
            "success_rate": 0.95,
        }
    )
    manifest["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(manifest)
    result = validate_autonomy_release_manifest(
        manifest,
        adapter_name="ashby",
        adapter_version="1.1.0",
    )
    assert result["passed"] is False
    assert "minimum_success_rate" in result["missing"]

    inconsistent = valid_manifest()
    inconsistent["reliability_window"]["success_rate"] = 0.99
    inconsistent["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(inconsistent)
    result = validate_autonomy_release_manifest(
        inconsistent,
        adapter_name="ashby",
        adapter_version="1.1.0",
    )
    assert result["passed"] is False
    assert "success_rate_consistent" in result["missing"]


def test_retry_breaker_recovery_and_policy_controls_fail_closed():
    manifest = valid_manifest()
    manifest["retry_policy"]["max_automatic_retries_per_attempt"] = 2
    manifest["circuit_breaker"]["verified"] = False
    manifest["recovery_drills"]["browser_death"] = False
    manifest["policy_readiness"]["kill_switch"] = False
    manifest["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(manifest)

    result = validate_autonomy_release_manifest(
        manifest,
        adapter_name="ashby",
        adapter_version="1.1.0",
    )

    assert result["passed"] is False
    assert "retry_limit" in result["missing"]
    assert "circuit_breaker_verified" in result["missing"]
    assert "recovery_browser_death" in result["missing"]
    assert "policy_kill_switch" in result["missing"]


def test_machine_readable_schema_tracks_contract_shape():
    schema_path = Path(__file__).parents[1] / "schemas" / "autonomy-release.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    requirements = autonomy_release_contract_requirements()

    assert schema["properties"]["schema_version"]["const"] == AUTONOMY_RELEASE_SCHEMA_VERSION
    assert schema["properties"]["reliability_window"]["properties"]["attempts"]["minimum"] == MIN_RELIABILITY_ATTEMPTS
    assert schema["properties"]["reliability_window"]["properties"]["success_rate"]["minimum"] == MIN_SUCCESS_RATE
    assert set(requirements["required_recovery_drills"]) == set(
        schema["properties"]["recovery_drills"]["required"]
    )
    assert set(requirements["required_policy_controls"]) <= set(
        schema["properties"]["policy_readiness"]["required"]
    )
