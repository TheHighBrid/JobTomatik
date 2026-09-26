from pathlib import Path


def test_completion_evidence_records_persisted_status():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "persisted JobTomatik status" in contract
