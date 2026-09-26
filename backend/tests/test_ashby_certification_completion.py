from pathlib import Path


def test_completion_requires_status_and_duplicate_proof():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "persisted JobTomatik status" in contract
    assert "duplicate-suppression result" in contract
