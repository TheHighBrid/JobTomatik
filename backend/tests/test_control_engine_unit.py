from app.services.control_engine import (
    OptionRecord,
    certification_manifest,
    match_answer_candidates_to_options,
    match_answers_to_options,
    parse_policy_answers,
)
from app.services.control_policy import resolve_control_policy


def _policy(key, answer, *, phrases=None, policy_id=1):
    return {
        "id": policy_id,
        "canonical_key": key,
        "category": "custom",
        "sensitivity": "standard",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": phrases or [],
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T10:00:00",
    }


def test_parse_policy_answers_preserves_commas_but_supports_explicit_lists():
    assert parse_policy_answers("Ottawa, Ontario") == ["Ottawa, Ontario"]
    assert parse_policy_answers('["Remote", "Hybrid"]') == ["Remote", "Hybrid"]
    assert parse_policy_answers("Remote; Hybrid") == ["Remote", "Hybrid"]


def test_exact_and_boolean_option_matching():
    options = [
        OptionRecord(key="yes", label="Yes", value="Y"),
        OptionRecord(key="no", label="No", value="N"),
    ]
    assert match_answers_to_options(["yes"], options, allow_multiple=False).matched[0].key == "yes"
    assert match_answers_to_options(["false"], options, allow_multiple=False).matched[0].key == "no"


def test_ambiguous_partial_match_is_rejected():
    options = [
        OptionRecord(key="citizen", label="Yes - citizen", value="citizen"),
        OptionRecord(key="resident", label="Yes - permanent resident", value="resident"),
    ]
    result = match_answers_to_options(["Yes"], options, allow_multiple=False)
    assert result.ok is False
    assert "Yes" in result.ambiguous_answers


def test_multi_answer_requires_every_answer_to_match():
    options = [
        OptionRecord(key="remote", label="Remote", value="remote"),
        OptionRecord(key="hybrid", label="Hybrid", value="hybrid"),
        OptionRecord(key="onsite", label="On-site", value="onsite"),
    ]
    result = match_answers_to_options(["Remote", "Hybrid"], options, allow_multiple=True)
    assert result.ok is True
    assert {item.key for item in result.matched} == {"remote", "hybrid"}

    missing = match_answers_to_options(["Remote", "Moon base"], options, allow_multiple=True)
    assert missing.ok is False
    assert missing.missing_answers == ["Moon base"]


def test_ordered_fallback_uses_first_answer_that_matches_unambiguously():
    options = [
        OptionRecord(key="female", label="Female", value="female"),
        OptionRecord(key="male", label="Male", value="male"),
        OptionRecord(key="decline", label="Prefer not to answer", value="decline"),
    ]
    result = match_answer_candidates_to_options(
        ["Man", "Male", "Prefer not to answer"],
        options,
        allow_multiple=False,
    )
    assert result.ok is True
    assert result.matched[0].key == "male"


def test_ordered_fallback_never_selects_an_unlisted_option():
    options = [
        OptionRecord(key="asian", label="Asian", value="asian"),
        OptionRecord(key="white", label="White", value="white"),
    ]
    result = match_answer_candidates_to_options(
        ["North African", "Middle Eastern", "Prefer not to answer"],
        options,
        allow_multiple=False,
    )
    assert result.ok is False
    assert result.matched == []


def test_exact_custom_phrase_overrides_broad_catalog_family():
    result = resolve_control_policy(
        "Preferred relocation city",
        [
            _policy("willing_to_relocate", "Yes", policy_id=1),
            _policy(
                "custom.relocation_city",
                "Montreal",
                phrases=["preferred relocation city"],
                policy_id=2,
            ),
        ],
    )

    assert result["can_autofill"] is True
    assert result["answer"] == "Montreal"
    assert result["policy"]["canonical_key"] == "custom.relocation_city"


def test_legacy_privacy_and_terms_consent_controls_remain_classified():
    privacy = resolve_control_policy(
        "I agree to the privacy policy",
        [_policy("privacy_consent", "Yes")],
    )
    terms = resolve_control_policy(
        "I agree to the application terms",
        [_policy("terms_consent", "No")],
    )

    assert privacy["can_autofill"] is True
    assert privacy["answer"] == "Yes"
    assert terms["can_autofill"] is True
    assert terms["answer"] == "No"


def test_certification_manifest_never_overclaims_universal_coverage():
    manifest = certification_manifest()
    assert manifest["certification_level"] == "standards_fixture_certified"
    assert manifest["universally_certified"] is False
    assert all(manifest["safety_invariants"].values())
