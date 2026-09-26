from pathlib import Path


def test_current_adapter_remains_source_of_truth():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "current mainline architecture" in contract
    assert Path("backend/app/services/ats_ashby.py").exists()
