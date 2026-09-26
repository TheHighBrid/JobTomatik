from pathlib import Path


def test_runbook_targets_dedicated_branch():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "`agent/ashby-certification`" in text
