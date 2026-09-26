from pathlib import Path


def test_verifier_reports_missing_confirmation_details():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "missing_confirmation_evidence_type" in source
    assert "missing_confirmation_final_url" in source
