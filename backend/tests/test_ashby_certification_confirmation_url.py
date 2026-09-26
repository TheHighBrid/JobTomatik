from pathlib import Path


def test_confirmation_final_url_is_required_by_verifier():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("confirmation_final_url")' in verifier
    assert '"missing_confirmation_final_url"' in verifier
