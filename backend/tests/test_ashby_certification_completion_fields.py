from pathlib import Path


def test_completion_record_names_required_facts():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    for phrase in ("application id", "Ashby target", "confirmation evidence type/final URL", "persisted JobTomatik status", "duplicate-suppression result"):
        assert phrase in text
