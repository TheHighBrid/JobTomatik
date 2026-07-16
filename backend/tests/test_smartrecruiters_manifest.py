from app.services.ats_registry import ats_certification_manifest
from app.services.ats_smartrecruiters import (
    SMARTRECRUITERS_SCREENING_FIELD_TYPES,
    SmartRecruitersAdapter,
)


FULL_FORM_CERTIFIED = "fixture_live_inspection_synthetic_and_handoff_certified"
SMARTRECRUITERS_CERTIFIED = (
    "fixture_live_metadata_preform_handoff_and_resume_certified"
)


def test_smartrecruiters_base_manifest_remains_truthful_and_fail_closed():
    manifest = SmartRecruitersAdapter().manifest()
    assert manifest["name"] == "smartrecruiters"
    assert manifest["version"] == "1.0.0"
    assert manifest["certification_level"] == "fixture_pending_live_certification"
    assert manifest["application_api_requires_x_smart_token"] is True
    assert manifest["live_certification"]["public_form_smoke"] == "pending"
    assert manifest["live_certification"]["synthetic_full_form_exercise"] == "pending"
    assert manifest["live_certification"]["resumable_handoff"] == "pending"
    assert manifest["live_certification"]["final_submit_clicked"] is False
    assert "SINGLE_SELECT" in SMARTRECRUITERS_SCREENING_FIELD_TYPES
    assert "INFORMATION" in SMARTRECRUITERS_SCREENING_FIELD_TYPES


def test_registered_smartrecruiters_reports_only_earned_boundaries():
    manifest = ats_certification_manifest()
    adapters = {item["name"]: item for item in manifest["adapters"]}
    assert set(adapters) >= {"greenhouse", "lever", "ashby", "smartrecruiters"}
    assert adapters["lever"]["certification_level"] == FULL_FORM_CERTIFIED
    assert adapters["ashby"]["certification_level"] == FULL_FORM_CERTIFIED

    smartrecruiters = adapters["smartrecruiters"]
    assert smartrecruiters["version"] == "1.1.0"
    assert smartrecruiters["certification_level"] == SMARTRECRUITERS_CERTIFIED
    live = smartrecruiters["live_certification"]
    assert live["public_posting_metadata"] == "certified"
    assert live["current_live_sample"]["posting_count"] == 3
    assert live["current_live_sample"]["company_count"] == 2
    assert live["current_live_sample"]["certified_boundary"] == (
        "pre_form_anti_bot_handoff"
    )
    assert live["live_hosted_form_controls"] == (
        "not_reached_due_to_pre_form_datadome"
    )
    assert live["synthetic_live_full_form_exercise"] == (
        "not_reached_due_to_pre_form_datadome"
    )
    assert live["pre_form_anti_bot_handoff"] == "certified"
    assert live["fixture_full_form_behavior"] == "certified"
    assert live["fixture_verified_resume_upload"] is True
    assert live["resumable_handoff"] == "fixture_certified"
    assert live["live_full_form_certified"] is False
    assert live["bypass_attempted"] is False
    assert live["final_submit_clicked"] is False

    invariants = manifest["safety_invariants"]
    assert invariants["smartrecruiters_application_api_requires_explicit_token"] is True
    assert invariants["smartrecruiters_datadome_is_manual_handoff_only"] is True
    assert invariants["smartrecruiters_live_full_form_not_claimed"] is True
