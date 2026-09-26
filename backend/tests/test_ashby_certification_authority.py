from pathlib import Path


def test_certification_does_not_bypass_normal_submission_policy():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "submit only under the normal authorized submission policy" in contract
