from pathlib import Path


def test_branch_head_final_run_requires_genuine_intent():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "genuinely intends to apply to" in runbook
