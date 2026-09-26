from pathlib import Path


def test_adapter_extracts_validation_errors():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "async def extract_validation_errors(" in source
    assert '".validation-error"' in source
    assert "[aria-invalid=\"true\"]" in source
