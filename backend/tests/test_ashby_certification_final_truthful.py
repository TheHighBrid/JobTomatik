from pathlib import Path


def test_certification_state_is_truthful_until_final_gate():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in contract
    assert 'certification_level = "fixture_pending_live_certification"' in adapter
