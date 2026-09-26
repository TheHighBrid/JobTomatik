from pathlib import Path


def test_hosted_application_support_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"hosted_application_page": True' in adapter
