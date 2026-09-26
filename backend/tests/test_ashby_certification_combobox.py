from pathlib import Path


def test_searchable_combobox_support_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"searchable_comboboxes": True' in adapter
