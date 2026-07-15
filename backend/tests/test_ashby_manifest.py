from app.services.ats_ashby import ASHBY_FORM_FIELD_TYPES, AshbyAdapter
from app.services.ats_registry import ats_certification_manifest


EXPECTED_CERTIFICATION = "fixture_live_inspection_synthetic_and_handoff_certified"


def test_ashby_base_manifest_remains_truthful_and_fail_closed():
    manifest = AshbyAdapter().manifest()
    assert manifest["name"] == "ashby"
    assert manifest["version"] == "1.0.0"
    assert manifest["certification_level"] == "fixture_pending_live_certification"
    assert manifest["live_certification"]["public_form_smoke"] == "pending"
    assert manifest["live_certification"]["synthetic_full_form_exercise"] == "pending"
    assert manifest["live_certification"]["resumable_handoff"] == "pending"
    assert manifest["live_certification"]["final_submit_clicked"] is False
    assert set(manifest["official_form_field_types"]) == ASHBY_FORM_FIELD_TYPES


def test_registered_ashby_manifest_reports_only_earned_boundaries():
    manifest = ats_certification_manifest()
    adapters = {item["name"]: item for item in manifest["adapters"]}
    assert set(adapters) >= {"greenhouse", "lever", "ashby"}
    assert adapters["lever"]["certification_level"] == EXPECTED_CERTIFICATION

    ashby = adapters["ashby"]
    assert ashby["version"] == "1.1.0"
    assert ashby["certification_level"] == EXPECTED_CERTIFICATION
    assert ashby["live_certification"]["public_form_smoke"] == "certified"
    assert ashby["live_certification"]["synthetic_full_form_exercise"] == "certified"
    assert ashby["live_certification"]["resumable_handoff"] == "certified"
    assert ashby["live_certification"]["credentialed_form_definition_support"] == (
        "fixture_certified_optional_runtime_validation"
    )
    assert ashby["live_certification"]["exact_name_system_field_alias_verified"] is True
    assert ashby["live_certification"]["verified_resume_upload"] is True
    assert ashby["live_certification"]["final_submit_clicked"] is False

    invariants = manifest["safety_invariants"]
    assert invariants["private_api_credentials_not_required_for_public_form_ci"] is True
    assert invariants["exact_ashby_name_alias_only"] is True
