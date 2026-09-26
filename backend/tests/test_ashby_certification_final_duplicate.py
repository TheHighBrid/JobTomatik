from pathlib import Path


def test_branch_head_requires_duplicate_suppression():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "A confirmed application must not be offered or submitted again" in contract
