from pathlib import Path


def test_contract_has_required_real_runtime_gate():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "## Required real-runtime gate" in text
