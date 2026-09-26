from pathlib import Path


def test_next_control_rejects_submit_terms():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'reject_terms=("submit", "apply", "finish", "linkedin")' in adapter
