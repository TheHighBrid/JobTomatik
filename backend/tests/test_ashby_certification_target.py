from pathlib import Path


def test_verifier_binds_evidence_to_ashby_host():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert '!= "jobs.ashbyhq.com"' in source
    assert '"target_not_ashby"' in source
