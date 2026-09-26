from pathlib import Path


def test_verifier_requires_duplicate_suppression():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("duplicate_submission_suppressed") is not True' in verifier
