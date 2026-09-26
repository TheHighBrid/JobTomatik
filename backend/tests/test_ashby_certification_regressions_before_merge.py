from pathlib import Path


def test_regressions_required_before_merge():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "regression suites before merge" in text
