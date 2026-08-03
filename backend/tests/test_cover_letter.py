from app.services.cover_letter import _fallback_cover_letter


def test_fallback_cover_letter_uses_only_supplied_employers():
    letter = _fallback_cover_letter(
        {"title": "Fraud Analyst", "company": "Example Bank"},
        {
            "full_name": "Mohamed Alem",
            "current_role": "banking professional",
            "years_experience": "5",
            "employment_history": (
                "TD Bank | Customer service\n"
                "RBC | Banking operations\n"
                "BMO | Loan Officer"
            ),
        },
    )
    for employer in ("TD Bank", "RBC", "BMO"):
        assert employer in letter
    assert "Scotiabank" not in letter
    assert "Tangerine" not in letter


def test_fallback_does_not_invent_profile_facts_when_history_missing():
    letter = _fallback_cover_letter(
        {"title": "Fraud Analyst", "company": "Example Bank"},
        {},
    )
    assert "TD Bank" not in letter
    assert "Tangerine" not in letter
    assert "Mohamed Alem" not in letter
    assert "several years" not in letter
    assert "bilingual" not in letter.lower()
    assert "I am writing to apply for the Fraud Analyst position at Example Bank." in letter
