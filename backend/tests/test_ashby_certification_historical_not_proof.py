from pathlib import Path


def test_historical_evidence_is_context_not_proof():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "useful regression context but is not accepted as proof" in text
