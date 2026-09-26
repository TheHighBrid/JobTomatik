from pathlib import Path


def test_embedded_iframe_support_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"embedded_iframe": True' in adapter
