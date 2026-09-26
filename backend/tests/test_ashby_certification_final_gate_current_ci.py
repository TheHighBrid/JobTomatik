from pathlib import Path


def test_physical_gate_has_ci_contract():
    assert Path(".github/workflows/ashby-real-certification-contract.yml").exists()
