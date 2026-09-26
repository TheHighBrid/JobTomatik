from pathlib import Path


def test_adapter_has_confirmation_detector():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "async def detect_confirmation(" in source
