from pathlib import Path


def test_physical_gate_has_explicit_contract():
    assert Path("docs/ASHBY_REAL_CERTIFICATION.md").exists()
