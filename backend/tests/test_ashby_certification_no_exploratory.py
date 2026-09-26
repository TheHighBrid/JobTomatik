from pathlib import Path


def test_final_gate_is_not_exploratory_debugging():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "not an exploratory debugging procedure" in text
