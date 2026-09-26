from pathlib import Path


def test_runbook_requires_one_physical_run_not_repetitive_user_testing():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "## One physical run" in runbook
