from pathlib import Path


def test_confirmation_evidence_type_is_required_by_verifier():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("confirmation_evidence_type")' in verifier
    assert '"missing_confirmation_evidence_type"' in verifier
