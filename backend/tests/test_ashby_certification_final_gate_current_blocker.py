from pathlib import Path


def test_remaining_blocker_is_physical_proof():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "This is the final gate" in runbook
