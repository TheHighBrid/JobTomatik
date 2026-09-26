from pathlib import Path


def test_real_gate_requires_fields_and_uploads():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "fill supported fields and uploads" in text
