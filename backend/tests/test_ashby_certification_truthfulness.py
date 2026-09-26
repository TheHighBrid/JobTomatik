from pathlib import Path


def test_truthful_status_until_evidence_exists():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
    assert not Path("evidence/ashby-real-certification.json").exists()
