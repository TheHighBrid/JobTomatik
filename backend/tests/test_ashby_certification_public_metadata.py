from pathlib import Path


def test_public_metadata_inspection_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"public_board_metadata_inspection": True' in adapter
