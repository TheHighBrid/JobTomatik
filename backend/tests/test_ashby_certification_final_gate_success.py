from pathlib import Path


def test_physical_proof_requires_confirmation_and_applied():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "genuine Ashby confirmation evidence" in runbook
    assert "`Applied`" in runbook
