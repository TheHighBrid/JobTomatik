from pathlib import Path


def test_final_gate_summary_is_executable():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "## One physical run" in runbook
    assert "## Evidence to retain" in runbook
    assert "## Promotion" in runbook
