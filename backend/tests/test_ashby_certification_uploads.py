from pathlib import Path


def test_verified_upload_support_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"verified_uploads": True' in adapter
