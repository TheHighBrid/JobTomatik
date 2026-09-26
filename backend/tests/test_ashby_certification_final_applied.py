from pathlib import Path


def test_branch_head_final_run_requires_applied_reconciliation():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "reconcile the record to `Applied`" in runbook
