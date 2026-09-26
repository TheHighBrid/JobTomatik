from pathlib import Path


def test_physical_gate_continues_same_application():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Continue the same application" in runbook
