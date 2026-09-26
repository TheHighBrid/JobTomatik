from pathlib import Path


def test_prepare_can_reveal_application_link():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'a[href*="/application"]' in adapter
