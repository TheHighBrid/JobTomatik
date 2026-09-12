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
    {
        "canonical_key": "sponsorship_required",
        "label": "Requires employer sponsorship",
        "category": "sponsorship",
        "sensitivity": "legal",
        "description": "Whether you currently or later require visa or immigration sponsorship.",
        "patterns": [
            r"require (?:employer )?sponsorship",
            r"sponsorship.{0,80}(?:now|future)",
            r"(?:now|future).{0,80}sponsorship",
            r"work permit or visa.{0,80}work legally",
        ],
        "setup_group": "Eligibility",
        "suggested_answers": ["No", "Yes"],
        "fallback_suggestions": ["I do not require sponsorship", "No sponsorship required"],
        "default_mode": "answer",
    },
    {
        "canonical_key": "compensation_range_acceptance",
        "label": "Compensation range acceptance",
        "category": "compensation",
        "sensitivity": "sensitive",
        "description": "Whether an employer-stated pay range aligns with your expectations.",
        "patterns": [
            r"(?:hourly )?pay range.{0,120}align with your expectations",
            r"compensation range.{0,120}align with your expectations",
            r"salary range.{0,120}align with your expectations",
            r"does (?:this|the) range align with your expectations",
        ],
        "setup_group": "Work preferences",
        "suggested_answers": ["Yes", "No"],
        "fallback_suggestions": ["The range aligns with my expectations"],
        "default_mode": "ask_each_time",
    },
]
