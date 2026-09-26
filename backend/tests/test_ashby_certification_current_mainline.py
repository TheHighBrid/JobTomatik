from pathlib import Path


def test_certification_evidence_targets_current_architecture():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "current mainline architecture" in text
