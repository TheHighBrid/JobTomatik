from pathlib import Path


def test_physical_run_requires_same_application_resume():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Continue the same application" in runbook
