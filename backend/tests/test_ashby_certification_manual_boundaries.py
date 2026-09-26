from pathlib import Path


def test_manual_security_boundaries_remain_intact():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "CAPTCHA/MFA remains a manual boundary" in contract
    assert '"manual_captcha_handoff": True' in adapter
    assert '"manual_mfa_handoff": True' in adapter
