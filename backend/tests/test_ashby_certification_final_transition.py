from pathlib import Path


def test_branch_head_waits_for_completion_before_certified_transition():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Only then may this document and the adapter certification metadata be changed from IN PROGRESS to CERTIFIED" in contract
