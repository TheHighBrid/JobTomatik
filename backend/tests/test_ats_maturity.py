from app.services.ats_manifest import ats_certification_manifest
from app.services.ats_maturity import (
    AUTONOMY_RELEASE_GATES,
    AdapterMaturity,
    annotate_adapter_manifest,
    derive_adapter_maturity,
)
import hashlib

from app.services.autonomy_release_contract import (
    AUTONOMY_SIGNATURE_METHOD,
    MIN_DISTINCT_CONFIRMED_SUBMISSIONS,
    MIN_RELIABILITY_ATTEMPTS,
    REQUIRED_SHADOW_CHECKS,
    compute_autonomy_manifest_digest,
    compute_autonomy_manifest_signature,
)
from app.services import unattended_policy
from app.services import ats_maturity

TEST_SIGNING_KEY = "jobtomatik-day27-test-signing-key-0001"
TEST_ARTIFACTS = {
    "fixture_digest": b"retained fixture evidence",
    "evidence_digest": b"retained supervised submission ledger",
    "policy_digest": b"retained policy snapshot",
}
TEST_DIGESTS = {
    name: "sha256:" + hashlib.sha256(content).hexdigest()
    for name, content in TEST_ARTIFACTS.items()
}


def test_runtime_release_commit_must_match_attested_running_revision(monkeypatch):
    configured = "a" * 40
    running = "b" * 40
    monkeypatch.setattr(
        ats_maturity,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "autonomy_release_commit": configured,
                "autonomy_fixture_artifact": "fixture.json",
                "autonomy_evidence_artifact": "evidence.json",
                "autonomy_policy_artifact": "policy.json",
            },
        )(),
    )
    monkeypatch.setattr(
        ats_maturity,
        "runtime_identity_manifest",
        lambda: {"revision": running, "deployment_attested": True},
    )

    trusted_commit, _ = ats_maturity._runtime_release_identity()

    assert trusted_commit is None

    monkeypatch.setattr(
        ats_maturity,
        "runtime_identity_manifest",
        lambda: {"revision": configured.upper(), "deployment_attested": True},
    )
    trusted_commit, _ = ats_maturity._runtime_release_identity()
    assert trusted_commit == configured


def test_annotation_uses_one_certification_validation_snapshot(monkeypatch):
    release = {
        **{gate: True for gate in AUTONOMY_RELEASE_GATES},
        "approved": True,
        "approval_reference": "day27-test",
        "certification_manifest": {},
    }
    results = iter(
        [
            {"passed": True, "missing": []},
            {"passed": False, "missing": ["source.evidence_digest_verified"]},
        ]
    )
    calls = 0

    def changing_validation(*args, **kwargs):
        nonlocal calls
        calls += 1
        return next(results)

    monkeypatch.setattr(
        ats_maturity, "validate_autonomy_release_manifest", changing_validation
    )

    annotated = annotate_adapter_manifest(
        {"name": "example", "version": "1.0.0", "autonomy_release": release},
        trusted_release_commit="a" * 40,
    )

    assert calls == 1
    assert annotated["maturity"] == AdapterMaturity.CERTIFIED_AUTONOMOUS.value
    assert annotated["autonomous_submission_allowed"] is True
    assert annotated["release_gate_status"]["certified_autonomous"]["passed"] is True


def _autonomy_manifest(name="example", version="1.0.0", release_commit="a" * 40):
    manifest = {
        "schema_version": "autonomy_release_v1",
        "adapter": {"name": name, "version": version},
        "source": {
            "release_commit": release_commit,
            **TEST_DIGESTS,
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
            "approval_reference": "day27-owner-approval",
            "approved_for_commit": release_commit,
        },
        "integrity": {"algorithm": "sha256", "manifest_digest": ""},
        "attestation": {
            "method": AUTONOMY_SIGNATURE_METHOD,
            "key_id": "test-day27-key",
            "signature": "",
        },
    }
    manifest["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(manifest)
    manifest["attestation"]["signature"] = compute_autonomy_manifest_signature(
        manifest,
        TEST_SIGNING_KEY,
    )
    return manifest


def test_current_registry_maturity_snapshot_is_explicit():
    manifest = ats_certification_manifest()
    adapters = {item["name"]: item for item in manifest["adapters"]}

    assert {name: item["maturity"] for name, item in adapters.items()} == {
        "greenhouse": AdapterMaturity.DRY_RUN.value,
        "lever": AdapterMaturity.DRY_RUN.value,
        "ashby": AdapterMaturity.DRY_RUN.value,
        "smartrecruiters": AdapterMaturity.DETECT_ONLY.value,
        "workday": AdapterMaturity.DETECT_ONLY.value,
    }
    assert manifest["autonomous_adapters"] == []
    assert all(
        item["autonomous_submission_allowed"] is False
        for item in adapters.values()
    )
    assert manifest["safety_invariants"]["certification_level_is_descriptive_only"] is True


def test_certification_prose_cannot_promote_operational_maturity():
    manifest = {
        "name": "example",
        "supported_hosts": ["jobs.example.test"],
        "certification_level": "certified_autonomous",
        "live_certification": {
            "public_form_smoke": "certified",
            "final_submit_clicked": False,
        },
    }

    annotated = annotate_adapter_manifest(manifest)

    assert annotated["certification_level"] == "certified_autonomous"
    assert annotated["maturity"] == AdapterMaturity.DETECT_ONLY.value
    assert annotated["autonomous_submission_allowed"] is False
    assert annotated["release_gate_status"]["certified_autonomous"]["passed"] is False


def test_zero_submit_live_exercise_reaches_dry_run_only():
    manifest = {
        "name": "example",
        "version": "1.0.0",
        "supported_hosts": ["jobs.example.test"],
        "certification_level": "fixture_live_certified",
        "live_certification": {
            "synthetic_full_form_exercise": "certified",
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        },
    }

    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN


def test_autonomous_promotion_requires_gates_manifest_shadow_runs_and_trusted_signature():
    release = {gate: True for gate in AUTONOMY_RELEASE_GATES}
    manifest = {
        "name": "example",
        "version": "1.0.0",
        "supported_hosts": ["jobs.example.test"],
        "live_certification": {
            "synthetic_full_form_exercise": "certified",
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        },
        "autonomy_release": release,
    }

    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN

    release["approved"] = True
    release["approval_reference"] = "controlled-pilot-2026-07"
    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN

    release["certification_manifest"] = _autonomy_manifest()
    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN
    assert derive_adapter_maturity(
        manifest,
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    ) is AdapterMaturity.CERTIFIED_AUTONOMOUS

    incomplete_shadow = _autonomy_manifest()
    incomplete_shadow["shadow_runs"]["twenty_four_hour_unattended_passed"] = False
    incomplete_shadow["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(incomplete_shadow)
    incomplete_shadow["attestation"]["signature"] = compute_autonomy_manifest_signature(
        incomplete_shadow,
        TEST_SIGNING_KEY,
    )
    release["certification_manifest"] = incomplete_shadow
    assert derive_adapter_maturity(
        manifest,
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    ) is AdapterMaturity.DRY_RUN

    unreviewed = _autonomy_manifest()
    unreviewed["reliability_window"]["independently_reviewed_successes"] -= 1
    unreviewed["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(unreviewed)
    unreviewed["attestation"]["signature"] = compute_autonomy_manifest_signature(
        unreviewed,
        TEST_SIGNING_KEY,
    )
    release["certification_manifest"] = unreviewed
    assert derive_adapter_maturity(
        manifest,
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    ) is AdapterMaturity.DRY_RUN


def test_tampered_wrong_version_or_wrong_signature_cannot_promote():
    release = {gate: True for gate in AUTONOMY_RELEASE_GATES}
    release.update(
        {
            "approved": True,
            "approval_reference": "day27-test",
            "certification_manifest": _autonomy_manifest(),
        }
    )
    manifest = {
        "name": "example",
        "version": "1.0.0",
        "supported_hosts": ["jobs.example.test"],
        "live_certification": {
            "synthetic_full_form_exercise": "certified",
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        },
        "autonomy_release": release,
    }
    assert derive_adapter_maturity(
        manifest,
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    ) is AdapterMaturity.CERTIFIED_AUTONOMOUS

    release["certification_manifest"]["reliability_window"]["duplicate_submissions"] = 1
    assert derive_adapter_maturity(
        manifest,
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    ) is AdapterMaturity.DRY_RUN

    release["certification_manifest"] = _autonomy_manifest(version="0.9.0")
    assert derive_adapter_maturity(
        manifest,
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    ) is AdapterMaturity.DRY_RUN

    release["certification_manifest"] = _autonomy_manifest()
    assert derive_adapter_maturity(
        manifest,
        trusted_signing_key="different-trusted-signing-key-000000000",
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    ) is AdapterMaturity.DRY_RUN


def test_generic_adapter_requires_a_specific_implementation_before_promotion():
    release = {gate: True for gate in AUTONOMY_RELEASE_GATES}
    release.update(
        {
            "approved": True,
            "approval_reference": "invalid-generic-release",
            "certification_manifest": _autonomy_manifest(name="generic"),
        }
    )
    annotated = annotate_adapter_manifest(
        {
            "name": "generic",
            "version": "1.0.0",
            "supported_hosts": [],
            "autonomy_release": release,
        },
        trusted_signing_key=TEST_SIGNING_KEY,
        trusted_release_commit="a" * 40,
        trusted_source_artifacts=TEST_ARTIFACTS,
    )

    assert annotated["maturity"] == AdapterMaturity.UNSUPPORTED.value
    assert annotated["autonomous_submission_allowed"] is False


def test_live_maturity_reader_never_falls_back_to_certification_level(monkeypatch):
    monkeypatch.setattr(
        unattended_policy,
        "ats_certification_manifest",
        lambda: {
            "adapters": [
                {
                    "name": "ashby",
                    "certification_level": "fixture_live_inspection_synthetic_and_handoff_certified",
                }
            ]
        },
    )

    maturities = unattended_policy.live_platform_maturities()
    assert maturities["ashby"] is None
    assert maturities["generic"] is None


def test_ats_certification_endpoint_exposes_canonical_maturity(client):
    response = client.get("/api/system/ats-certification")

    assert response.status_code == 200
    payload = response.json()
    assert payload["maturity_model"] == "roadmap_issue_13_v1"
    assert payload["autonomous_adapters"] == []
    assert all("maturity" in item for item in payload["adapters"])
    assert all(
        item["release_gate_status"]["certified_autonomous"]["certification_manifest"]["passed"] is False
        for item in payload["adapters"]
    )


def test_operations_readiness_exposes_product_goal_and_adapter_maturity(client):
    response = client.get("/api/system/operations-readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_goal"] == "fully_autonomous_evidence_backed_real_submission"
    assert payload["adapter_maturities"] == {
        "greenhouse": AdapterMaturity.DRY_RUN.value,
        "lever": AdapterMaturity.DRY_RUN.value,
        "ashby": AdapterMaturity.DRY_RUN.value,
        "smartrecruiters": AdapterMaturity.DETECT_ONLY.value,
        "workday": AdapterMaturity.DETECT_ONLY.value,
    }
    assert payload["autonomous_adapters"] == []
    assert payload["autonomous_adapter_count"] == 0
    assert payload["invariants"]["canonical_adapter_maturity_required"] is True
