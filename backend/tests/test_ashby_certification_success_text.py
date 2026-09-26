from pathlib import Path


def test_confirmation_retains_success_text():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "confirmation_text=text[:500]" in adapter
