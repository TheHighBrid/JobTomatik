from pathlib import Path


def test_runbook_requires_genuine_application_intent():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "role the operator genuinely intends to apply to" in runbook
