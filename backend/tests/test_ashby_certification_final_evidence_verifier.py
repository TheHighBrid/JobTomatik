from pathlib import Path


def test_final_evidence_has_executable_verifier():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "python backend/scripts/verify_ashby_real_certification.py evidence/ashby-real-certification.json" in runbook
