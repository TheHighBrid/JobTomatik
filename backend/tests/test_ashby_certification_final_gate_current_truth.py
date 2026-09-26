from pathlib import Path


def test_current_certification_truth_is_consistent():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
    assert '"mode": "not_yet_certified"' in source
    assert '"final_submit_clicked": False' in source
