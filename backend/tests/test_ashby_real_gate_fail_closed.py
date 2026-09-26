from pathlib import Path


def test_fail_closed_boundaries_are_explicit():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Missing or ambiguous confirmation must remain pending/manual review" in text
    assert "Unknown answers must not be invented" in text
    assert "CAPTCHA/MFA remains a manual boundary" in text
    assert "must not silently select an unrelated browser tab" in text
    assert "must not be offered or submitted again" in text
