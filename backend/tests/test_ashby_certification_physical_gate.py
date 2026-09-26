from pathlib import Path


def test_physical_run_is_final_gate():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "This is the final gate, not an exploratory debugging procedure" in runbook
