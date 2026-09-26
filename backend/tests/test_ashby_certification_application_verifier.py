from pathlib import Path


def test_verifier_requires_application_id():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("application_id")' in verifier
    assert '"missing_application_id"' in verifier
