from pathlib import Path


def test_branch_head_requires_retained_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "## Evidence to retain" in runbook
    assert "evidence/ashby-real-certification.json" in runbook
