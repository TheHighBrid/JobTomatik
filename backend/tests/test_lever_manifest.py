from app.services.ats_registry import ats_certification_manifest


def test_lever_manifest_is_truthful_about_official_api_boundary():
    manifest = ats_certification_manifest()
    adapters = {item["name"]: item for item in manifest["adapters"]}

    assert "greenhouse" in adapters
    assert "lever" in adapters
    lever = adapters["lever"]

    assert lever["official_posting_endpoint"] == "GET /v0/postings/{site}/{posting_id}?mode=json"
    assert lever["official_custom_questions_exposed"] is False
    assert lever["capabilities"]["custom_question_dom_inspection"] is True
    assert lever["capabilities"]["manual_captcha_handoff"] is True
    assert lever["capabilities"]["manual_mfa_handoff"] is True
    assert lever["live_certification"]["final_submit_clicked"] is False
    assert manifest["safety_invariants"]["official_api_gaps_are_reported_not_guessed"] is True
