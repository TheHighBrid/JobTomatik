from pathlib import Path


def test_dynamic_field_support_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"dynamic_conditional_fields": True' in adapter
