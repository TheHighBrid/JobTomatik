from pathlib import Path


def test_real_certification_contract_is_ready():
    assert Path("docs/ASHBY_REAL_CERTIFICATION.md").is_file()
