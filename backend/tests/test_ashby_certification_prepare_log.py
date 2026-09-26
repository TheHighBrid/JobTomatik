from pathlib import Path


def test_prepare_logs_application_reveal():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"action": "ashby_application_revealed"' in adapter
