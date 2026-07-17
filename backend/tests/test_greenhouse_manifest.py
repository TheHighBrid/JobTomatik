from app.services.ats_greenhouse import GreenhouseAdapter


def test_greenhouse_manifest_reports_completed_synthetic_live_exercise():
    manifest = GreenhouseAdapter().manifest()

    assert manifest["version"] == "1.1.1"
    assert manifest["certification_level"] == (
        "fixture_live_inspection_and_synthetic_exercise_certified"
    )
    assert manifest["capabilities"]["searchable_comboboxes"] is True
    assert manifest["capabilities"]["manual_captcha_handoff"] is True

    live = manifest["live_certification"]
    assert live["public_form_smoke"] == "certified"
    assert live["synthetic_full_form_exercise"] == "certified"
    assert live["latest_certified_boundary"] == "captcha_detected_post_fill_pre_action"
    assert live["verified_resume_upload"] is True
    assert live["final_submit_clicked"] is False
    assert "manual_challenge_handoff" in live["accepted_safe_outcomes"]
