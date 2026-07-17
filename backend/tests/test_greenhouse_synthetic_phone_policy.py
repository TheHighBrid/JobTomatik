from app.services.control_policy import resolve_control_policy
from app.services.greenhouse_certification import (
    build_synthetic_profile,
    choose_synthetic_answer,
)


def _policy(policy_id, key, answer, phrase):
    return {
        "id": policy_id,
        "canonical_key": key,
        "category": "synthetic_certification",
        "sensitivity": "synthetic",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": [phrase],
        "scope": "platform",
        "scope_value": "greenhouse",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T00:00:00Z",
    }


def test_custom_policy_phrase_does_not_match_inside_ethnicity():
    policies = [
        _policy(1, "custom.city", "Ottawa, Ontario, Canada", "City"),
        _policy(
            2,
            "custom.hispanic",
            "Decline To Self Identify",
            "Are you Hispanic/Latino?",
        ),
    ]

    result = resolve_control_policy(
        "hispanic_ethnicity | off | Are you Hispanic/Latino? | Select...",
        policies,
    )

    assert result["can_autofill"] is True
    assert result["answer"] == "Decline To Self Identify"
    assert result["policy"]["canonical_key"] == "custom.hispanic"


def test_hispanic_synthetic_answer_prefers_decline_option():
    answer = choose_synthetic_answer(
        "Are you Hispanic/Latino?",
        ["Yes", "No", "Decline To Self Identify"],
        multiple=False,
    )

    assert answer == "Decline To Self Identify"


def test_synthetic_profile_includes_phone_country_widget_policy():
    profile = build_synthetic_profile({"questions": []})

    assert profile["phone"] == "6135550199"
    assert profile["country"] == "Canada"
    phone_country = next(
        policy
        for policy in profile["answer_policies"]
        if policy["canonical_key"] == "custom.synthetic_phone_country"
    )
    assert phone_country["answer_label"] == "Canada +1"
    assert phone_country["match_phrases"] == ["country | off | Country* | Phone"]
