from pathlib import Path


def test_verifier_requires_answer_policy_proof():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("unknown_answer_policy_respected") is not True' in verifier
