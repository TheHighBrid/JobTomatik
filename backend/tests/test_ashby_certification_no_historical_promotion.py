from pathlib import Path


def test_historical_dry_run_alone_cannot_certify():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "historical dry-run evidence alone" in contract
