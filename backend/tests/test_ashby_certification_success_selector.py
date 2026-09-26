from pathlib import Path


def test_confirmation_checks_success_selectors():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '[data-testid*="confirmation" i]' in adapter
    assert '[data-testid*="success" i]' in adapter
