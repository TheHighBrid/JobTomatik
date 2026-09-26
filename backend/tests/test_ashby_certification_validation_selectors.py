from pathlib import Path


def test_validation_selectors_cover_alert_and_invalid_controls():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '[role="alert"]' in adapter
    assert '[aria-invalid="true"]' in adapter
