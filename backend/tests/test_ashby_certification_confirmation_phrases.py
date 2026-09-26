from pathlib import Path


def test_confirmation_phrases_cover_success_states():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    for phrase in ("thank you for applying", "application submitted", "application received", "we have received your application"):
        assert phrase in adapter
