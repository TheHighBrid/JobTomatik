from pathlib import Path


def test_verifier_requires_retained_tab_resume_proof():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("retained_tab_resume_proven") is not True' in verifier
