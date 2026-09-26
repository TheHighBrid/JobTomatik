from pathlib import Path


def test_second_submission_remaining_possible_invalidates_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "a second submission remains possible" in runbook
