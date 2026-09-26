from pathlib import Path


def test_verifier_validates_target_host():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'urlparse(target).hostname' in source
    assert 'jobs.ashbyhq.com' in source
