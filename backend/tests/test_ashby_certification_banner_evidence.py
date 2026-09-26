from pathlib import Path


def test_phrase_confirmation_emits_success_banner_evidence():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'evidence_type="success_banner"' in adapter
