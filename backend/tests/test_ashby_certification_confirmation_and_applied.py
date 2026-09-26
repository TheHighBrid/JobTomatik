from pathlib import Path


def test_physical_success_requires_confirmation_and_applied():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "genuine Ashby confirmation evidence" in text
    assert "reconcile the record to `Applied`" in text
