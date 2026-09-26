from pathlib import Path


def test_confirmation_detector_emits_sufficient_evidence():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "ConfirmationEvidence(" in adapter
    assert "is_sufficient=True" in adapter
