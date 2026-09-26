from pathlib import Path


def test_verifier_binds_ashby_adapter():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("adapter") != "ashby"' in verifier
