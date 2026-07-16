from app.services.ats_registry import ats_certification_manifest
from app.services.ats_smartrecruiters import (
    SMARTRECRUITERS_SCREENING_FIELD_TYPES,
    SmartRecruitersAdapter,
)


CERTIFIED = "fixture_live_inspection_synthetic_and_handoff_certified"


def test_smartrecruiters_base_manifest_is_truthful_before_live_promotion():
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


def test_registry_includes_smartrecruiters_without_overwriting_certified_adapters():
    manifest = ats_certification_manifest()
    adapters = {item["name"]: item for item in manifest["adapters"]}
    assert set(adapters) >= {"greenhouse", "lever", "ashby", "smartrecruiters"}
    assert adapters["lever"]["certification_level"] == CERTIFIED
    assert adapters["ashby"]["certification_level"] == CERTIFIED
    assert adapters["smartrecruiters"]["certification_level"] == (
        "fixture_pending_live_certification"
    )
    assert manifest["framework_version"] == "1.3.0"
    assert manifest["safety_invariants"][
        "smartrecruiters_application_api_requires_explicit_token"
    ] is True
