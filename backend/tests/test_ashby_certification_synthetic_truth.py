from pathlib import Path


def test_pre_certification_synthetic_exercise_is_pending():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"synthetic_full_form_exercise": "pending"' in adapter
