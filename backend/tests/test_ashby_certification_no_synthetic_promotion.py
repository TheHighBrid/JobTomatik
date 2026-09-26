from pathlib import Path


def test_synthetic_evidence_alone_cannot_certify():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "synthetic" in contract
    assert "evidence alone" in contract
