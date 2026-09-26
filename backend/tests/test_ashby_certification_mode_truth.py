from pathlib import Path


def test_pre_certification_mode_is_not_yet_certified():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"mode": "not_yet_certified"' in adapter
