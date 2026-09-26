from pathlib import Path


def test_real_gate_requires_authorized_submission_policy():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "submit only under the normal authorized submission policy" in text
