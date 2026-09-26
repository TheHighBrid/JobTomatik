from pathlib import Path


def test_branch_head_preserves_unknown_answer_policy():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Unknown answers must not be invented" in contract
