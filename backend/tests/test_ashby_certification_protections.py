from pathlib import Path


def test_normal_protections_stay_enabled():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "duplicate-suppression protections enabled" in text
