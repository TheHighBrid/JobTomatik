from pathlib import Path


def test_pending_record_invalidates_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "record remains pending" in runbook
