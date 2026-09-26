from pathlib import Path


def test_ashby_adapter_exposes_required_certification_capabilities():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"hosted_application_page": True' in source
    assert '"embedded_iframe": True' in source
    assert '"multi_step": True' in source
    assert '"verified_uploads": True' in source
    assert '"confirmation_detection": True' in source
    assert '"manual_captcha_handoff": True' in source
    assert '"manual_mfa_handoff": True' in source
