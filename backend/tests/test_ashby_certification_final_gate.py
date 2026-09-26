from pathlib import Path


def test_completion_requires_real_run():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Only then may this document and the adapter certification metadata be changed from IN PROGRESS to CERTIFIED" in contract
