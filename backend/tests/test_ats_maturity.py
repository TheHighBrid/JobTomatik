from app.services.ats_manifest import ats_certification_manifest
from app.services.ats_maturity import (
    AUTONOMY_RELEASE_GATES,
    AdapterMaturity,
    annotate_adapter_manifest,
    derive_adapter_maturity,
)
from app.services.autonomy_release_contract import compute_autonomy_manifest_digest
from app.services import unattended_policy


def _autonomy_manifest(name="example", version="1.0.0", release_commit="a" * 40):
    manifest = {
        "schema_version": "autonomy_release_v1",
        "adapter": {"name": name, "version": version},
        "source": {
            "release_commit": release_commit,
            "fixture_digest": "sha256:" + "1" * 64,
            "evidence_digest": "sha256:" + "2" * 64,
            "policy_digest": "sha256:" + "3" * 64,
        },
        "reliability_window": {
            "attempts": 20,
            "confirmed_successes": 20,
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
            "approval_reference": "day27-owner-approval",
            "approved_for_commit": release_commit,
        },
        "integrity": {"algorithm": "sha256", "manifest_digest": ""},
    }
    manifest["integrity"]["manifest_digest"] = compute_autonomy_manifest_digest(manifest)
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
    assert manifest["safety_invariants"][
        "certification_level_is_descriptive_only"
    ] is True


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


def test_autonomous_promotion_requires_approval_gates_and_immutable_manifest():
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
    # Day 27 closes the old loophole: approval plus booleans is still insufficient.
    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN

    release["certification_manifest"] = _autonomy_manifest()
    assert derive_adapter_maturity(manifest) is AdapterMaturity.CERTIFIED_AUTONOMOUS


def test_tampered_or_wrong_version_manifest_cannot_promote():
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
    assert derive_adapter_maturity(manifest) is AdapterMaturity.CERTIFIED_AUTONOMOUS

    release["certification_manifest"]["reliability_window"]["duplicate_submissions"] = 1
    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN

    release["certification_manifest"] = _autonomy_manifest(version="0.9.0")
    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN


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
        }
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
