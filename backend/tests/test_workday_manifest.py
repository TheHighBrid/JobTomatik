from app.services.ats_registry import ats_certification_manifest
from app.services.ats_workday import WorkdayAdapter


FULL_CERTIFIED = "fixture_live_inspection_synthetic_and_handoff_certified"
SMARTRECRUITERS_CERTIFIED = (
    "fixture_live_metadata_preform_handoff_and_resume_certified"
)
WORKDAY_CERTIFIED = (
    "fixture_live_metadata_apply_adventure_and_handoff_certified"
)


def test_workday_base_manifest_remains_truthful_outside_registry_promotion():
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


def test_registry_includes_bounded_workday_promotion_without_overclaiming():
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

    workday = adapters["workday"]
    assert workday["version"] == "1.1.0"
    assert workday["certification_level"] == WORKDAY_CERTIFIED
    live = workday["live_certification"]
    assert live["public_cxs_metadata"] == "certified"
    assert live["apply_adventure_manual_path"] == "certified"
    assert live["current_live_sample"]["posting_count"] == 3
    assert live["current_live_sample"]["tenant_count"] == 3
    assert live["synthetic_live_outcome"] == "pre_form_manual_handoff"
    assert live["synthetic_live_fields_filled"] == 0
    assert live["synthetic_live_upload_attempted"] is False
    assert live["fixture_verified_resume_upload"] is True
    assert live["resumable_handoff"] == "fixture_certified"
    assert live["live_full_form_certified"] is False
    assert live["credentials_entered"] is False
    assert live["account_created"] is False
    assert live["last_application_reused"] is False
    assert live["bypass_attempted"] is False
    assert live["final_submit_clicked"] is False

    assert manifest["framework_version"] == "1.4.0"
    invariants = manifest["safety_invariants"]
    assert invariants["workday_login_and_account_creation_are_manual"] is True
    assert invariants["workday_target_evidence_excludes_query_and_fragment"] is True
    assert invariants["workday_apply_adventure_uses_manual_path_only"] is True
    assert invariants["workday_prior_application_is_never_reused"] is True
    assert invariants["workday_live_full_form_not_claimed"] is True
