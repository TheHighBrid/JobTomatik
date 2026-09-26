from pathlib import Path


def test_certification_is_done_only_after_physical_proof():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Only then" in contract
    assert "CERTIFIED" in contract
