from pathlib import Path


def test_branch_head_final_run_retains_captured_facts():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "using facts captured by the run" in runbook
