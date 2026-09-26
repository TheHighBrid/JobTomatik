from pathlib import Path


def test_completion_evidence_records_confirmation_type_and_url():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "confirmation evidence type/final URL" in contract
