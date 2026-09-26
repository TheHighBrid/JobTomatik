from pathlib import Path


def test_branch_head_contract_is_fail_closed():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "## Fail-closed requirements" in contract
