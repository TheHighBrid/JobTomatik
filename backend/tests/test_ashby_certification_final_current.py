from pathlib import Path


def test_branch_head_targets_current_mainline_architecture():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "current mainline architecture" in contract
