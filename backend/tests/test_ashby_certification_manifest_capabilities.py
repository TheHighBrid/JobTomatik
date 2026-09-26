from pathlib import Path


def test_manifest_exposes_certification_relevant_capabilities():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    for capability in ("hosted_application_page", "embedded_iframe", "multi_step", "verified_uploads", "validation_extraction", "confirmation_detection", "manual_captcha_handoff", "manual_mfa_handoff"):
        assert f'"{capability}": True' in adapter
