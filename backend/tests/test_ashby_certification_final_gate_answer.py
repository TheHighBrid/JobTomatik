from pathlib import Path


def test_physical_proof_uses_answer_vault():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Answer Vault" in runbook
