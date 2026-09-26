from pathlib import Path


def test_manifest_does_not_claim_completed_live_certification():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"mode": "not_yet_certified"' in source
    assert '"public_form_smoke": "pending"' in source
    assert '"resumable_handoff": "pending"' in source
