from pathlib import Path


def test_certification_endpoint_requires_completion_evidence():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "## Completion evidence" in contract
    assert "Only then" in contract
