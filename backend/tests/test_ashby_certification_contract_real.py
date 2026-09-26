from pathlib import Path


def test_contract_is_real_runtime_not_fixture_gate():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "real-runtime certification" in text
    assert "not certified by fixture, synthetic, or historical dry-run evidence alone" in text
