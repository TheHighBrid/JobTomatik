from pathlib import Path


def test_real_gate_starts_from_real_target():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "resolve a real Ashby job/application target" in text
