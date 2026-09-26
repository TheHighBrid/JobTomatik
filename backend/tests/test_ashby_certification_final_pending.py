from pathlib import Path


def test_branch_head_keeps_ambiguous_result_pending():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "remain pending/manual review, never `applied`" in contract
