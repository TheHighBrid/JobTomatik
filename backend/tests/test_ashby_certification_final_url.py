from pathlib import Path


def test_confirmation_retains_final_url():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "final_url=current_url" in adapter
