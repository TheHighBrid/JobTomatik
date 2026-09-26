from pathlib import Path


def test_physical_gate_success_is_confirmation_plus_applied():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "genuine Ashby confirmation evidence" in runbook
    assert "reconcile the record to `Applied`" in runbook
