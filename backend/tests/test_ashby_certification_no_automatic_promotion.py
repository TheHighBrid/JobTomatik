from pathlib import Path


def test_runbook_separates_evidence_from_promotion():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "## Promotion" in runbook
    assert "Only after the physical evidence passes" in runbook
