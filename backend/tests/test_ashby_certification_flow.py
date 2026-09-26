from pathlib import Path


def test_physical_run_uses_normal_workflow():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "allow the normal workflow to proceed" in text
