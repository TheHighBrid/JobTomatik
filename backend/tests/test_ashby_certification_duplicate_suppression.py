from pathlib import Path


def test_confirmed_application_cannot_be_offered_again():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "must not be offered or submitted again" in contract
