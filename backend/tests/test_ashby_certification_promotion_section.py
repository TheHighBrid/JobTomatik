from pathlib import Path


def test_runbook_has_promotion_stage():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "## Promotion" in runbook
