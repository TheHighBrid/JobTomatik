from pathlib import Path


def test_final_plan_has_executable_evidence_gate():
    assert Path("backend/scripts/verify_ashby_real_certification.py").exists()
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "The verifier must exit zero" in runbook
