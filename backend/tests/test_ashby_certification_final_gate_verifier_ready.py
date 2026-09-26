from pathlib import Path


def test_verifier_is_ready_for_physical_evidence():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "def verify(payload: dict)" in source
    assert "return 1 if blockers else 0" in source
