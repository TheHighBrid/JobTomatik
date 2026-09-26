from pathlib import Path


def test_custom_question_inspection_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"custom_question_dom_inspection": True' in adapter
