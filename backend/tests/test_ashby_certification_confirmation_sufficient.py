from pathlib import Path


def test_verifier_requires_sufficient_confirmation():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("confirmation_sufficient") is not True' in verifier
