from pathlib import Path


def test_physical_runbook_is_ready():
    assert Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").is_file()
