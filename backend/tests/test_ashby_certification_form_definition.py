from pathlib import Path


def test_form_definition_validation_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"credentialed_form_definition_validation": True' in adapter
