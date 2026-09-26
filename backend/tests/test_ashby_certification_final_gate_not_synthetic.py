from pathlib import Path


def test_final_gate_cannot_be_satisfied_by_synthetic_evidence_alone():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "not certified by fixture, synthetic, or historical dry-run evidence alone" in contract
