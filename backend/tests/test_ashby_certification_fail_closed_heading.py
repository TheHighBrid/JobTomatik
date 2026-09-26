from pathlib import Path


def test_contract_has_fail_closed_section():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "## Fail-closed requirements" in text
