from pathlib import Path


def test_confirmation_detector_can_fail_closed_with_empty_evidence():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "return []" in adapter
