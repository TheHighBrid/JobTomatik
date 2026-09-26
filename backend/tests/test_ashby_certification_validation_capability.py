from pathlib import Path


def test_validation_extraction_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"validation_extraction": True' in adapter
