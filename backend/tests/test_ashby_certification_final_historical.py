from pathlib import Path


def test_branch_head_rejects_historical_evidence_as_current_proof():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "is not accepted as proof of the current Android/native-Chrome runtime" in contract
