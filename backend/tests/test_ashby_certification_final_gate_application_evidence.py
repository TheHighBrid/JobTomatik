from pathlib import Path


def test_completion_evidence_records_application_identity():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "application id" in contract
    assert "Ashby target" in contract
