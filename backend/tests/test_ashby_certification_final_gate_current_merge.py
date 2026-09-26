from pathlib import Path


def test_physical_gate_merges_only_after_regressions():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "regression suites before merge" in runbook
