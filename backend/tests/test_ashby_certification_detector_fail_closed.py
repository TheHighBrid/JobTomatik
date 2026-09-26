from pathlib import Path


def test_confirmation_detector_has_empty_evidence_fallback():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    section = adapter.split("async def detect_confirmation(", 1)[1].split("def manifest", 1)[0]
    assert "return []" in section
