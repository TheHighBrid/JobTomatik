from pathlib import Path


def test_confirmed_application_not_offered_or_submitted_again():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "A confirmed application must not be offered or submitted again" in text
