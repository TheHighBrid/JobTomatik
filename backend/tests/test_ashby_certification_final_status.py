from pathlib import Path


def test_branch_head_status_is_in_progress_until_physical_run():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in text
