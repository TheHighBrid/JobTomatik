from pathlib import Path


def test_runbook_title_is_physical_certification():
    first = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8").splitlines()[0]
    assert first == "# Ashby physical certification runbook"
