from pathlib import Path


def test_branch_head_final_run_requires_genuine_confirmation():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "genuine Ashby confirmation evidence" in runbook
