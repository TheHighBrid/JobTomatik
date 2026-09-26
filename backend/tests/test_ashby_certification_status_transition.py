from pathlib import Path


def test_status_transition_is_explicit():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "IN PROGRESS to CERTIFIED" in text
