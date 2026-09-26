from pathlib import Path


def test_physical_gate_keeps_protections_enabled():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "duplicate-suppression protections enabled" in runbook
