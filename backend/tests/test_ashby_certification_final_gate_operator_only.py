from pathlib import Path


def test_remaining_gate_is_operator_authorized_physical_application():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "operator-authorized application" in contract
    assert "## One physical run" in runbook
