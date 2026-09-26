from pathlib import Path


def test_verifier_derives_certified_from_zero_blockers():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert '"certified": not blockers' in source
