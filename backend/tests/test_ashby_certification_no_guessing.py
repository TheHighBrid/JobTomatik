from pathlib import Path


def test_guessed_answers_invalidate_physical_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "unknown answers were guessed" in runbook
