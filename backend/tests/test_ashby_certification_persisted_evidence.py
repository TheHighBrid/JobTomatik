from pathlib import Path


def test_contract_requires_persisted_confirmation():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "persist confirmation evidence" in contract
