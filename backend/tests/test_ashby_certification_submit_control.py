from pathlib import Path


def test_adapter_has_explicit_submit_detection():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "async def find_submit_button(" in source
    assert "Submit Application" in source
