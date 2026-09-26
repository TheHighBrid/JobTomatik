from pathlib import Path


def test_real_gate_requires_duplicate_prevention():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "prevent another submission attempt for the confirmed application" in text
