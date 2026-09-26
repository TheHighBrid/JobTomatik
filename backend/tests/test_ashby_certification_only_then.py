from pathlib import Path


def test_only_then_can_certification_metadata_change():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Only then may this document and the adapter certification metadata be changed" in text
