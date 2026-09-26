from pathlib import Path


def test_captcha_and_mfa_stay_manual():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "CAPTCHA/MFA remains a manual boundary" in text
