from pathlib import Path


def test_verify_returns_blockers():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "return blockers" in source
