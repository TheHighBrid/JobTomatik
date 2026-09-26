from pathlib import Path


def test_unknown_answers_cannot_be_invented():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Unknown answers must not be invented" in text
