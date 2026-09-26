from pathlib import Path


def test_branch_head_preserves_manual_security_boundaries():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "CAPTCHA/MFA remains a manual boundary" in contract
