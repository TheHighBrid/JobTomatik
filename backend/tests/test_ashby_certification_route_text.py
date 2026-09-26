from pathlib import Path


def test_route_confirmation_requires_application_text():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"application" in normalized' in adapter
