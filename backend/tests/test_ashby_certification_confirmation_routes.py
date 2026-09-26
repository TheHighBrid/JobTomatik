from pathlib import Path


def test_confirmation_routes_cover_common_success_paths():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "thanks|thank-you|confirmation|submitted" in adapter
