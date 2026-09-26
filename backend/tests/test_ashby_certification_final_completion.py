from pathlib import Path


def test_branch_head_enumerates_completion_evidence():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "## Completion evidence" in contract
