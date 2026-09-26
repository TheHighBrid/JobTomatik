from pathlib import Path


def test_physical_target_requires_genuine_intent():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "genuinely intends to apply to" in text
