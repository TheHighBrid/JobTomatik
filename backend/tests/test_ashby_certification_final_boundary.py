from pathlib import Path


def test_final_certification_boundary_is_explicit():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Only then" in contract
    assert "IN PROGRESS to CERTIFIED" in contract
