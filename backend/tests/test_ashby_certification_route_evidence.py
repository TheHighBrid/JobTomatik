from pathlib import Path


def test_route_confirmation_emits_confirmation_page_evidence():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'evidence_type="confirmation_page"' in adapter
