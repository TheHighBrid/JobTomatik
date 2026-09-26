from pathlib import Path


def test_branch_head_defines_one_final_physical_gate():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "## One physical run" in runbook
    assert "This is the final gate" in runbook
