from pathlib import Path


def test_prepared_branch_does_not_falsely_claim_certification():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
