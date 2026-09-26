from pathlib import Path


def test_runbook_enumerates_invalid_evidence_cases():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    for phrase in ("confirmation is ambiguous", "record remains pending", "unrelated tab", "unknown answers were guessed", "second submission remains possible"):
        assert phrase in text
