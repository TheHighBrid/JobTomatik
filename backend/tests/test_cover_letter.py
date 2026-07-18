from app.services.cover_letter import _fallback_cover_letter


def test_fallback_cover_letter_names_banking_employers():
    letter = _fallback_cover_letter(
        {"title": "Fraud Analyst", "company": "Example Bank"},
        {
            "full_name": "Mohamed Alem",
            "current_role": "banking professional",
            "years_experience": "5",
            "employment_history": (
                "TD Bank | Customer service\n"
                "RBC | Banking operations\n"
                "BMO | Loan Officer\n"
                "Scotiabank | Collections\n"
                "Tangerine | Collections"
            ),
        },
    )
    for employer in ("TD Bank", "RBC", "BMO", "Scotiabank", "Tangerine"):
        assert employer in letter


def test_fallback_uses_default_banking_employers_when_history_missing():
    letter = _fallback_cover_letter(
        {"title": "Fraud Analyst", "company": "Example Bank"},
        {"full_name": "Mohamed Alem"},
    )
    assert "TD Bank" in letter
    assert "Tangerine" in letter
