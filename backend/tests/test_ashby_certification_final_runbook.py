from pathlib import Path


def test_branch_head_runbook_requires_physical_evidence():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Only after the physical evidence passes" in text
