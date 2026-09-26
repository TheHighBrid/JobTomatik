from pathlib import Path


def test_prepare_recognizes_application_route():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'if urlparse(current_url).path.rstrip("/").endswith("/application")' in adapter
