from pathlib import Path


def test_verifier_exposes_verify_function():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "def verify(payload: dict) -> list[str]:" in source
