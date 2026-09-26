from pathlib import Path


def test_physical_run_uses_existing_answer_vault_flow():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "answer it through the existing Answer Vault flow" in runbook
