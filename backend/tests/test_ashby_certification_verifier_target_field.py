from pathlib import Path


def test_verifier_reads_target_url():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("target_url")' in source
