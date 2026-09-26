from pathlib import Path


def test_runbook_requires_real_intended_application_and_evidence_verifier():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "real Ashby-hosted role the operator genuinely intends to apply to" in runbook
    assert "Answer Vault" in runbook
    assert "same application" in runbook
    assert "genuine Ashby confirmation evidence" in runbook
    assert "evidence/ashby-real-certification.json" in runbook
    assert "verify_ashby_real_certification.py" in runbook
