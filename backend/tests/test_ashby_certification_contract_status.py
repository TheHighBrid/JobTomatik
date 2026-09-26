from pathlib import Path


def test_contract_begins_in_progress():
    lines = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8").splitlines()
    assert "Status: IN PROGRESS" in lines[:6]
