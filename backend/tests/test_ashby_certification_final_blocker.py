from pathlib import Path


def test_physical_run_is_explicit_final_gate():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "This is the final gate" in runbook
