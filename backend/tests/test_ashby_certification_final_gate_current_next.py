from pathlib import Path


def test_remaining_gate_is_explicitly_physical():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "# Ashby physical certification runbook" in runbook
    assert "## One physical run" in runbook
