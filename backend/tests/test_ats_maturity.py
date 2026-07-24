from app.services.ats_manifest import ats_certification_manifest
from app.services.ats_maturity import (
    AUTONOMY_RELEASE_GATES,
    AdapterMaturity,
    annotate_adapter_manifest,
    derive_adapter_maturity,
)
from app.services import unattended_policy


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
        "supported_hosts": ["jobs.example.test"],
        "certification_level": "fixture_live_certified",
        "live_certification": {
            "synthetic_full_form_exercise": "certified",
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        },
    }

    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN


def test_autonomous_promotion_requires_approval_and_every_release_gate():
    release = {gate: True for gate in AUTONOMY_RELEASE_GATES}
    manifest = {
        "name": "example",
        "supported_hosts": ["jobs.example.test"],
        "live_certification": {
            "synthetic_full_form_exercise": "certified",
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        },
        "autonomy_release": release,
    }

    # Passing booleans alone are insufficient without an explicit approval
    # reference that can be reviewed and audited.
    assert derive_adapter_maturity(manifest) is AdapterMaturity.DRY_RUN

    release["approved"] = True
    release["approval_reference"] = "controlled-pilot-2026-07"
    assert derive_adapter_maturity(manifest) is AdapterMaturity.CERTIFIED_AUTONOMOUS


def test_generic_adapter_requires_a_specific_implementation_before_promotion():
    release = {gate: True for gate in AUTONOMY_RELEASE_GATES}
    release.update({"approved": True, "approval_reference": "invalid-generic-release"})
    annotated = annotate_adapter_manifest(
        {
            "name": "generic",
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
