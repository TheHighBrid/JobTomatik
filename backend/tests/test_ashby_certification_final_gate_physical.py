from pathlib import Path


def test_certification_still_requires_physical_proof():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "physical evidence" in runbook
