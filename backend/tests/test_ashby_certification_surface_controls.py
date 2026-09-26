from pathlib import Path


def test_surface_resolution_checks_form_controls():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    for selector in ('button[type="submit"]', 'input[type="submit"]', "textarea", "select"):
        assert selector in adapter
