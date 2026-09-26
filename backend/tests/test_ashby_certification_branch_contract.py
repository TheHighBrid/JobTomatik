from pathlib import Path


def test_runbook_requires_validation_before_promotion():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Only after the physical evidence passes" in runbook
    assert "before merge" in runbook
