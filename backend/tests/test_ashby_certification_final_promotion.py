from pathlib import Path


def test_branch_head_gates_promotion_on_passing_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Only after the physical evidence passes" in runbook
