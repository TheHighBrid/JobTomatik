"""Phase B answer-policy catalog additions discovered during live Lever certification.

Keep these entries narrow and employer-question shaped. Unknown questions must still
fail closed and require owner review.
"""

PHASE_B_QUESTION_CATALOG = [
    {
        "canonical_key": "current_canadian_province",
        "label": "Current Canadian province",
        "category": "location",
        "sensitivity": "standard",
        "description": "The Canadian province or territory where you are currently based.",
        "patterns": [
            r"which canadian province are you currently based in",
            r"which province are you currently based in",
            r"current(?:ly)? based in (?:which )?canadian province",
            r"current canadian province",
            r"province (?:or territory )?(?:are you|you are) currently based in",
        ],
        "setup_group": "Location",
        "suggested_answers": [
            "Alberta",
            "British Columbia",
            "Manitoba",
            "New Brunswick",
            "Newfoundland and Labrador",
            "Northwest Territories",
            "Nova Scotia",
            "Nunavut",
            "Ontario",
            "Prince Edward Island",
            "Quebec",
            "Saskatchewan",
            "Yukon",
        ],
        "fallback_suggestions": [
            "AB", "BC", "MB", "NB", "NL", "NT", "NS", "NU", "ON", "PE", "QC", "SK", "YT"
        ],
        "default_mode": "answer",
    },
]
