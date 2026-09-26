from pathlib import Path


def test_current_level_remains_pending():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'fixture_pending_live_certification' in source
