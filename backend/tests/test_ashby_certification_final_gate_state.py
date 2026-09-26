from pathlib import Path


def test_state_is_ready_for_physical_gate_but_not_certified():
    assert Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").exists()
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
