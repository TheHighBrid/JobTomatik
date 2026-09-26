from pathlib import Path


def test_verifier_requires_applied_status():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("persisted_status") != "applied"' in verifier
