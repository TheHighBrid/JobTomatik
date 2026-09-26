from pathlib import Path


def test_status_remains_in_progress_before_physical_completion():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
