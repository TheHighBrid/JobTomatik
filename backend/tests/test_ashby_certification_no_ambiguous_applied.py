from pathlib import Path


def test_ambiguous_confirmation_stays_pending():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Missing or ambiguous confirmation must remain pending/manual review, never `applied`" in text
