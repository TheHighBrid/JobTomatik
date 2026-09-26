from pathlib import Path


def test_current_status_remains_in_progress():
    assert "Status: IN PROGRESS" in Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
