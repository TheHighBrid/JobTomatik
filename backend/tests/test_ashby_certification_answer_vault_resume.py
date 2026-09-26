from pathlib import Path


def test_answer_vault_then_same_application():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "answer it through the existing Answer Vault flow" in text
    assert "Continue the same application" in text
