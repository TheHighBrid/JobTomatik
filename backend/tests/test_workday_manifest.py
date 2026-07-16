from app.services.ats_registry import ats_certification_manifest
from app.services.ats_workday import WorkdayAdapter


FULL_CERTIFIED = "fixture_live_inspection_synthetic_and_handoff_certified"
SMARTRECRUITERS_CERTIFIED = (
    "fixture_live_metadata_preform_handoff_and_resume_certified"
)


def test_workday_base_manifest_is_truthful_before_promotion():
    manifest = WorkdayAdapter().manifest()
    assert manifest["name"] == "workday"
    assert manifest["version"] == "1.0.0"
    assert manifest["certification_level"] == "fixture_pending_live_certification"
    assert manifest["public_metadata_endpoint"].startswith("GET /wday/cxs/")
    assert manifest["capabilities"]["bounded_apply_transition"] is True
    assert manifest["capabilities"]["manual_login_handoff"] is True
    assert manifest["capabilities"]["manual_account_creation_handoff"] is True
    assert manifest["live_certification"]["public_metadata_inspection"] == "pending"
    assert manifest["live_certification"]["hosted_form_inspection"] == "pending"
    assert manifest["live_certification"]["synthetic_full_form_exercise"] == "pending"
    assert manifest["live_certification"]["resumable_handoff"] == "pending"
    assert manifest["live_certification"]["final_submit_clicked"] is False


def test_registry_includes_pending_workday_without_overwriting_prior_adapters():
    manifest = ats_certification_manifest()
    adapters = {item["name"]: item for item in manifest["adapters"]}
    assert set(adapters) >= {
        "greenhouse", "lever", "ashby", "smartrecruiters", "workday"
    }
    assert adapters["lever"]["certification_level"] == FULL_CERTIFIED
    assert adapters["ashby"]["certification_level"] == FULL_CERTIFIED
    assert adapters["smartrecruiters"]["certification_level"] == (
        SMARTRECRUITERS_CERTIFIED
    )
    assert adapters["workday"]["certification_level"] == (
        "fixture_pending_live_certification"
    )
    assert manifest["framework_version"] == "1.4.0"
    invariants = manifest["safety_invariants"]
    assert invariants["workday_login_and_account_creation_are_manual"] is True
    assert invariants["workday_target_evidence_excludes_query_and_fragment"] is True
