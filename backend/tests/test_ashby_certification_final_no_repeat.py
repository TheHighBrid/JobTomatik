from pathlib import Path


def test_final_gate_is_one_physical_run():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "## One physical run" in runbook
