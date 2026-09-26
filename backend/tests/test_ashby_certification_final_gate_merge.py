from pathlib import Path


def test_merge_waits_for_regression_validation():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "regression suites before merge" in runbook
