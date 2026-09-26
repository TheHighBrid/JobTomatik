from pathlib import Path


def test_final_gate_has_explicit_certification_endpoint():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "IN PROGRESS to CERTIFIED" in contract
