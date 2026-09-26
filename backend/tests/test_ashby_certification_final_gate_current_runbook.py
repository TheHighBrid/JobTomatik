from pathlib import Path


def test_physical_gate_has_operator_runbook():
    assert Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").exists()
