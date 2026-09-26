from pathlib import Path


def test_surface_resolution_prefers_application_frame():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "preferring application frames" in adapter
    assert 'endswith("/application")' in adapter
