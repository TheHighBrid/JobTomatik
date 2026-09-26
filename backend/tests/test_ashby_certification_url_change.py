from pathlib import Path


def test_route_confirmation_requires_url_change():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "current_url != before_url" in adapter
