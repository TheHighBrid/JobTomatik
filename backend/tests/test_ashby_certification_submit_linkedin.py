from pathlib import Path


def test_submit_detection_rejects_linkedin():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'reject_terms=("linkedin",)' in adapter
