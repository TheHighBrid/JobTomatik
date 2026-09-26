from pathlib import Path


def test_current_manifest_remains_pending():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"mode": "not_yet_certified"' in source
