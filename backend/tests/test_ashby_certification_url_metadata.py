from pathlib import Path


def test_success_banner_records_confirmation_url_metadata():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"confirmation_url": confirmation_url' in adapter
