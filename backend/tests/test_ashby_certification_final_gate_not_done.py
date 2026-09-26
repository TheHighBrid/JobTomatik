from pathlib import Path


def test_final_gate_remains_incomplete_until_physical_run():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
