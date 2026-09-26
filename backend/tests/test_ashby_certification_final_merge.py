from pathlib import Path


def test_branch_head_requires_regressions_before_merge():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "regression suites before merge" in runbook
