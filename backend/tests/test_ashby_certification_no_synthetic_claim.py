from pathlib import Path


def test_synthetic_only_result_is_explicitly_insufficient():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "not certified by fixture, synthetic, or historical dry-run evidence alone" in contract
