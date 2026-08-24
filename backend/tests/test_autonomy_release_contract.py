import copy
import json
from pathlib import Path

from app.services.autonomy_release_contract import (
    AUTONOMY_RELEASE_CONTRACT_VERSION,
    AUTONOMY_RELEASE_SCHEMA_VERSION,
    AUTONOMY_SIGNATURE_METHOD,
    MIN_DISTINCT_CONFIRMED_SUBMISSIONS,
    MIN_RELIABILITY_ATTEMPTS,
    MIN_SIGNING_KEY_BYTES,
    MIN_SUCCESS_RATE,
    REQUIRED_SHADOW_CHECKS,
    autonomy_release_contract_requirements,
    compute_autonomy_manifest_digest,
    compute_autonomy_manifest_signature,
    validate_autonomy_release_manifest,
)

TEST_SIGNING_KEY = "jobtomatik-day27-test-signing-key-0001"
TEST_ARTIFACTS = {
    "fixture_digest": b"retained fixture evidence",
    "evidence_digest": b"retained supervised submission ledger",
    "policy_digest": b"retained policy snapshot",
}


def _digest(content):
    import hashlib

    return "sha256:" + hashlib.sha256(content).hexdigest()


def _resign(manifest):
    manifest["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(manifest)
    manifest["attestation"]["signature"] = compute_autonomy_manifest_signature(
        manifest,
        TEST_SIGNING_KEY,
    )
    return manifest


def valid_manifest(*, adapter_name="ashby", adapter_version="1.1.0", commit="a" * 40):
    manifest = {
        "schema_version": AUTONOMY_RELEASE_SCHEMA_VERSION,
        "adapter": {"name": adapter_name, "version": adapter_version},
        "source": {
            "release_commit": commit,
            **{name: _digest(content) for name, content in TEST_ARTIFACTS.items()},
        },
        "reliability_window": {
            "evidence_type": "supervised_real_submission",
            "attempts": MIN_RELIABILITY_ATTEMPTS,
            "confirmed_successes": MIN_RELIABILITY_ATTEMPTS,
            "distinct_confirmed_submissions": MIN_DISTINCT_CONFIRMED_SUBMISSIONS,
            "independently_reviewed_successes": MIN_RELIABILITY_ATTEMPTS,
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
        "shadow_runs": {check: True for check in REQUIRED_SHADOW_CHECKS},
        "approval": {
            "approved": True,
            "approval_reference": "owner-day27-approval",
            "approved_for_commit": commit,
        },
        "integrity": {"algorithm": "sha256", "manifest_digest": ""},
        "attestation": {
            "method": AUTONOMY_SIGNATURE_METHOD,
            "key_id": "test-day27-key",
            "signature": "",
        },
    }
    return _resign(manifest)


def validate(manifest, *, version="1.1.0", signing_key=TEST_SIGNING_KEY):
    return validate_autonomy_release_manifest(
        manifest,
        adapter_name="ashby",
        adapter_version=version,
        trusted_signing_key=signing_key,
        trusted_release_commit=str(manifest.get("source", {}).get("release_commit") or ""),
        trusted_source_artifacts=TEST_ARTIFACTS,
    )


def test_valid_signed_manifest_satisfies_day27_contract():
    manifest = valid_manifest()
    result = validate(manifest)

    assert result["passed"] is True
    assert result["missing"] == []
    assert result["manifest_digest"] == compute_autonomy_manifest_digest(manifest)
    assert result["attestation_key_id"] == "test-day27-key"
    assert result["requirements"]["contract_version"] == AUTONOMY_RELEASE_CONTRACT_VERSION
    assert result["requirements"]["minimum_success_rate"] == MIN_SUCCESS_RATE
    assert result["requirements"]["minimum_reliability_attempts"] == MIN_RELIABILITY_ATTEMPTS
    assert result["requirements"]["minimum_distinct_confirmed_submissions"] == MIN_DISTINCT_CONFIRMED_SUBMISSIONS
    assert result["requirements"]["reliability_evidence_type"] == "supervised_real_submission"
    assert result["requirements"]["trusted_runtime_signing_key_required"] is True
    assert result["requirements"]["day39_promotion_blocked_until_shadow_checks_pass"] is True


def test_manifest_requires_a_separate_trusted_signing_key():
    manifest = valid_manifest()
    result = validate(manifest, signing_key=None)

    assert result["passed"] is False
    assert "trusted_signing_key" in result["missing"]
    assert "attestation_signature_matches" in result["missing"]


def test_wrong_signing_key_or_tampered_signature_fails_closed():
    manifest = valid_manifest()
    result = validate(
        manifest,
        signing_key="different-day27-signing-key-0000000000",
    )
    assert result["passed"] is False
    assert "attestation_signature_matches" in result["missing"]

    tampered = copy.deepcopy(manifest)
    tampered["attestation"]["signature"] = "hmac-sha256:" + "0" * 64
    result = validate(tampered)
    assert result["passed"] is False
    assert "attestation_signature_matches" in result["missing"]


def test_manifest_digest_detects_any_evidence_tampering():
    manifest = valid_manifest()
    tampered = copy.deepcopy(manifest)
    tampered["reliability_window"]["duplicate_submissions"] = 1

    result = validate(tampered)

    assert result["passed"] is False
    assert "zero_duplicate_submissions" in result["missing"]
    assert "manifest_digest_matches" in result["missing"]
    assert "attestation_signature_matches" in result["missing"]


def test_adapter_version_and_exact_commit_are_immutable_bindings():
    manifest = valid_manifest(commit="b" * 40)

    wrong_version = validate(manifest, version="1.2.0")
    assert wrong_version["passed"] is False
    assert "adapter_version" in wrong_version["missing"]

    wrong_commit = copy.deepcopy(manifest)
    wrong_commit["approval"]["approved_for_commit"] = "c" * 40
    _resign(wrong_commit)
    result = validate(wrong_commit)
    assert result["passed"] is False
    assert "approval_exact_release_commit" in result["missing"]
    assert result["checks"]["attestation_signature_matches"] is True


def test_empty_adapter_version_cannot_be_certified():
    manifest = valid_manifest(adapter_version="")
    result = validate(manifest, version="")
    assert result["passed"] is False
    assert "adapter_version" in result["missing"]


def test_release_commit_must_match_independent_runtime_identity():
    manifest = valid_manifest()
    result = validate_autonomy_release_manifest(
        manifest,
        adapter_name="ashby",
        adapter_version="1.1.0",
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="b" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    )
    assert result["passed"] is False
    assert "release_commit_matches_runtime" in result["missing"]


def test_source_digests_are_recomputed_from_retained_artifacts():
    manifest = valid_manifest()
    artifacts = dict(TEST_ARTIFACTS)
    artifacts["evidence_digest"] = b"fabricated replacement ledger"
    result = validate_autonomy_release_manifest(
        manifest,
        adapter_name="ashby",
        adapter_version="1.1.0",
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=artifacts,
    )
    assert result["passed"] is False
    assert "evidence_digest_matches_retained_artifact" in result["missing"]


def test_reliability_window_requires_supervised_distinct_reviewed_evidence():
    wrong_mode = valid_manifest()
    wrong_mode["reliability_window"]["evidence_type"] = "dry_run"
    _resign(wrong_mode)
    result = validate(wrong_mode)
    assert result["passed"] is False
    assert "supervised_reliability_evidence" in result["missing"]

    too_small = valid_manifest()
    too_small["reliability_window"].update(
        {
            "attempts": MIN_RELIABILITY_ATTEMPTS - 1,
            "confirmed_successes": MIN_RELIABILITY_ATTEMPTS - 1,
            "distinct_confirmed_submissions": MIN_DISTINCT_CONFIRMED_SUBMISSIONS - 1,
            "independently_reviewed_successes": MIN_RELIABILITY_ATTEMPTS - 1,
            "success_rate": 1.0,
        }
    )
    _resign(too_small)
    result = validate(too_small)
    assert result["passed"] is False
    assert "minimum_reliability_attempts" in result["missing"]
    assert "minimum_distinct_confirmed_submissions" in result["missing"]

    unreviewed = valid_manifest()
    unreviewed["reliability_window"]["independently_reviewed_successes"] -= 1
    _resign(unreviewed)
    result = validate(unreviewed)
    assert result["passed"] is False
    assert "all_successes_independently_reviewed" in result["missing"]


def test_reliability_window_requires_consistent_success_rate():
    below_rate = valid_manifest()
    below_rate["reliability_window"].update(
        {
            "attempts": 20,
            "confirmed_successes": 19,
            "distinct_confirmed_submissions": 19,
            "independently_reviewed_successes": 19,
            "success_rate": 0.95,
        }
    )
    _resign(below_rate)
    result = validate(below_rate)
    assert result["passed"] is False
    assert "minimum_success_rate" in result["missing"]

    inconsistent = valid_manifest()
    inconsistent["reliability_window"]["success_rate"] = 0.99
    _resign(inconsistent)
    result = validate(inconsistent)
    assert result["passed"] is False
    assert "success_rate_consistent" in result["missing"]


def test_retry_breaker_recovery_and_policy_controls_fail_closed():
    manifest = valid_manifest()
    manifest["retry_policy"]["max_automatic_retries_per_attempt"] = 2
    manifest["circuit_breaker"]["verified"] = False
    manifest["recovery_drills"]["browser_death"] = False
    manifest["policy_readiness"]["kill_switch"] = False
    _resign(manifest)

    result = validate(manifest)

    assert result["passed"] is False
    assert "retry_limit" in result["missing"]
    assert "circuit_breaker_verified" in result["missing"]
    assert "recovery_browser_death" in result["missing"]
    assert "policy_kill_switch" in result["missing"]


def test_every_roadmap_shadow_gate_is_required_for_promotion():
    manifest = valid_manifest()
    manifest["shadow_runs"]["final_submit_disabled"] = False
    manifest["shadow_runs"]["eight_hour_unattended_passed"] = False
    manifest["shadow_runs"]["no_leaked_sessions"] = False
    manifest["shadow_runs"]["zero_duplicate_tasks"] = False
    _resign(manifest)

    result = validate(manifest)

    assert result["passed"] is False
    assert "shadow_final_submit_disabled" in result["missing"]
    assert "shadow_eight_hour_unattended_passed" in result["missing"]
    assert "shadow_no_leaked_sessions" in result["missing"]
    assert "shadow_zero_duplicate_tasks" in result["missing"]


def test_short_signing_key_is_rejected_before_signature_generation():
    manifest = valid_manifest()
    try:
        compute_autonomy_manifest_signature(manifest, "short-key")
    except ValueError as exc:
        assert str(MIN_SIGNING_KEY_BYTES) in str(exc)
    else:
        raise AssertionError("short signing key unexpectedly accepted")


def test_machine_readable_schema_tracks_contract_shape():
    schema_path = Path(__file__).parents[1] / "schemas" / "autonomy-release.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    requirements = autonomy_release_contract_requirements()

    assert schema["properties"]["schema_version"]["const"] == AUTONOMY_RELEASE_SCHEMA_VERSION
    reliability = schema["properties"]["reliability_window"]
    assert reliability["properties"]["attempts"]["minimum"] == MIN_RELIABILITY_ATTEMPTS
    assert reliability["properties"]["distinct_confirmed_submissions"]["minimum"] == MIN_DISTINCT_CONFIRMED_SUBMISSIONS
    assert reliability["properties"]["evidence_type"]["const"] == "supervised_real_submission"
    assert reliability["properties"]["success_rate"]["minimum"] == MIN_SUCCESS_RATE
    assert schema["properties"]["attestation"]["properties"]["method"]["const"] == AUTONOMY_SIGNATURE_METHOD
    assert "attestation" in schema["required"]
    assert "shadow_runs" in schema["required"]
    assert "shadow_runs" in schema["properties"]
    assert set(requirements["required_recovery_drills"]) == set(
        schema["properties"]["recovery_drills"]["required"]
    )
    assert set(requirements["required_policy_controls"]) <= set(
        schema["properties"]["policy_readiness"]["required"]
    )
    assert set(requirements["required_shadow_checks"]) == set(
        schema["properties"]["shadow_runs"]["required"]
    )
    assert all(
        schema["properties"]["shadow_runs"]["properties"][check] == {"const": True}
        for check in REQUIRED_SHADOW_CHECKS
    )
