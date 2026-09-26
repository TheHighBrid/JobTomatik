from pathlib import Path


def test_fixture_evidence_alone_cannot_certify():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "not certified by fixture" in contract
