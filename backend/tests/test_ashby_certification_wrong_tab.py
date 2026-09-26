from pathlib import Path


def test_unrelated_tab_resume_invalidates_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "application resumed on an unrelated tab" in runbook
