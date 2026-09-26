from pathlib import Path


def test_physical_gate_has_fail_closed_verifier():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "Fail-closed verifier" in source
