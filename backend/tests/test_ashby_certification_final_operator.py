from pathlib import Path


def test_final_gate_is_operator_authorized_real_application():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "operator-authorized application" in contract
    assert "genuinely intends to apply to" in runbook
