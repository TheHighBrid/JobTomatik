from pathlib import Path


def test_certification_ci_contract_is_ready():
    assert Path(".github/workflows/ashby-real-certification-contract.yml").is_file()
