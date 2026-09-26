from pathlib import Path


def test_real_gate_requires_confirmation_persistence():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "persist confirmation evidence" in text
