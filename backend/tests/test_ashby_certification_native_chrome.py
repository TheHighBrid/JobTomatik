from pathlib import Path


def test_real_gate_names_retained_native_chrome():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "retained native Chrome runtime" in contract
