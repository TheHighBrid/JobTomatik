from pathlib import Path


def test_runbook_names_required_regression_surfaces():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    for surface in (
        "Ashby adapter",
        "handoff",
        "confirmation",
        "answer-policy",
        "duplicate-suppression",
        "certification-contract",
    ):
        assert surface in runbook
