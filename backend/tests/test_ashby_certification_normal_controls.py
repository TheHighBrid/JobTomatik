from pathlib import Path


def test_runbook_keeps_normal_protections_enabled():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "normal submission policy" in runbook
    assert "Answer Vault" in runbook
    assert "retained-tab recovery" in runbook
    assert "duplicate-suppression protections enabled" in runbook
