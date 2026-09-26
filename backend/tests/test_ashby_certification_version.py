from pathlib import Path


def test_current_adapter_version_is_explicit():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'ASHBY_ADAPTER_VERSION = "1.0.0"' in source
