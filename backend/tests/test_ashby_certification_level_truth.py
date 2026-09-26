from pathlib import Path


def test_certification_level_remains_pending_live_certification():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'certification_level = "fixture_pending_live_certification"' in adapter
