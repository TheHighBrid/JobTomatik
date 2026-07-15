from app.services.ats_ashby import ASHBY_FORM_FIELD_TYPES, AshbyAdapter
from app.services.ats_registry import ats_certification_manifest


def test_ashby_pending_manifest_is_truthful_before_live_promotion():
    manifest = AshbyAdapter().manifest()
    assert manifest["name"] == "ashby"
    assert manifest["version"] == "1.0.0"
    assert manifest["certification_level"] == "fixture_pending_live_certification"
    assert manifest["live_certification"]["public_form_smoke"] == "pending"
    assert manifest["live_certification"]["synthetic_full_form_exercise"] == "pending"
    assert manifest["live_certification"]["resumable_handoff"] == "pending"
    assert manifest["live_certification"]["final_submit_clicked"] is False
    assert set(manifest["official_form_field_types"]) == ASHBY_FORM_FIELD_TYPES


def test_registry_includes_ashby_without_overwriting_existing_certifications():
    manifest = ats_certification_manifest()
    adapters = {item["name"]: item for item in manifest["adapters"]}
    assert set(adapters) >= {"greenhouse", "lever", "ashby"}
    assert adapters["lever"]["certification_level"] == (
        "fixture_live_inspection_synthetic_and_handoff_certified"
    )
    assert adapters["ashby"]["certification_level"] == "fixture_pending_live_certification"
    assert manifest["safety_invariants"]["private_api_credentials_not_required_for_public_form_ci"] is True
