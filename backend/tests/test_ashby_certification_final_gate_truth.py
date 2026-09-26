from pathlib import Path


def test_tooling_readiness_does_not_equal_certification():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
