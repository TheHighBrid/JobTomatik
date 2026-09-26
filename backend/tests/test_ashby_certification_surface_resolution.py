from pathlib import Path


def test_adapter_resolves_application_surface():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "async def resolve_surface(" in source
    assert "preferring application frames" in source
