from pathlib import Path


def test_ashby_confirmation_detection_has_strong_success_signals():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    for phrase in (
        "thank you for applying",
        "thank you for your application",
        "application submitted",
        "application received",
        "we have received your application",
        "your application has been submitted",
    ):
        assert phrase in source
    assert 'evidence_type="confirmation_page"' in source
    assert 'evidence_type="success_banner"' in source
    assert "is_sufficient=True" in source
