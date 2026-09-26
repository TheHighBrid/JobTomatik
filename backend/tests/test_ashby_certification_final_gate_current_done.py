from pathlib import Path


def test_physical_gate_defines_exact_done_condition():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "IN PROGRESS to CERTIFIED" in contract
