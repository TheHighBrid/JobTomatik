from pathlib import Path


def test_pre_certification_public_smoke_is_pending():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"public_form_smoke": "pending"' in adapter
