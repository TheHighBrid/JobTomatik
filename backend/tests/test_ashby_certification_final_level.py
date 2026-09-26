from pathlib import Path


def test_branch_head_level_is_pending_live_certification():
    text = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'fixture_pending_live_certification' in text
