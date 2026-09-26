from pathlib import Path


def test_pre_certification_resumable_handoff_is_pending():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"resumable_handoff": "pending"' in adapter
