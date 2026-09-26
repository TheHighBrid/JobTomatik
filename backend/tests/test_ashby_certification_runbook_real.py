from pathlib import Path


def test_runbook_is_physical():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "# Ashby physical certification runbook" in text
    assert "## One physical run" in text
