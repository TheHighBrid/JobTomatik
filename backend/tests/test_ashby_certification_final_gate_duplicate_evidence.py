from pathlib import Path


def test_completion_evidence_records_duplicate_suppression():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "duplicate-suppression result" in contract
