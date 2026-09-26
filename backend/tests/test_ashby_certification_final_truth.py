from pathlib import Path


def test_branch_head_truthfully_waits_for_physical_gate():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
    assert '"mode": "not_yet_certified"' in adapter
    assert '"final_submit_clicked": False' in adapter
