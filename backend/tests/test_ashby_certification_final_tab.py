from pathlib import Path


def test_branch_head_requires_exact_retained_tab():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "exact retained application tab" in contract
