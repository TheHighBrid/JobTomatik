from pathlib import Path


def test_confirmation_detection_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"confirmation_detection": True' in adapter
