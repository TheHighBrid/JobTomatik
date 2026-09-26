from pathlib import Path


def test_branch_head_final_run_uses_answer_vault():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "existing Answer Vault flow" in runbook
