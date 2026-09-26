from pathlib import Path


def test_regression_surfaces_are_named():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Ashby adapter, handoff, confirmation, answer-policy, duplicate-suppression, and certification-contract" in text
