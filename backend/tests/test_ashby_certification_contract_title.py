from pathlib import Path


def test_contract_title_is_real_runtime_certification():
    first = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8").splitlines()[0]
    assert first == "# Ashby real-runtime certification"
