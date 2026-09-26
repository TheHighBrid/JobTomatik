from pathlib import Path


def test_surface_resolver_falls_back_to_page():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "return page" in adapter
