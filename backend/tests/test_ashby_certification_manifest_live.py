from pathlib import Path


def test_live_certification_manifest_is_pending():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"live_certification": {' in adapter
    assert '"mode": "not_yet_certified"' in adapter
