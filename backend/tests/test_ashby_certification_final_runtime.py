from pathlib import Path


def test_branch_head_requires_native_chrome_runtime():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "retained native Chrome runtime" in contract
