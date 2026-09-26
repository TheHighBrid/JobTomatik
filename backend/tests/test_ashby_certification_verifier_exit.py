from pathlib import Path


def test_verifier_exit_contract_is_fail_closed():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "return 1 if blockers else 0" in source
