from pathlib import Path


def test_contract_has_historical_evidence_section():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "## Historical evidence" in text
