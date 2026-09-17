from copy import deepcopy

import pytest

from app.services.control_policy import classify_control_question, resolve_control_policy


def _expect(condition, message):
    if not condition:
        raise AssertionError(message)


def _policy(*, policy_id=1, answer="Yes"):
    return {
        "id": policy_id,
        "canonical_key": "work_authorization",
        "category": "work_authorization",
        "sensitivity": "legal",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "fallback_answers": [],
        "match_phrases": [],
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-28T10:00:00Z",
        "provenance": "user_provided",
        "confidence": 1.0,
        "consent_metadata": {"autofill_authorized": True},
        "is_expired": False,
        "encryption_valid": True,
        "created_at": "2026-07-28T09:00:00Z",
        "updated_at": "2026-07-28T10:00:00Z",
    }


def _resolve(policy):
    return resolve_control_policy(
        "Are you legally authorized to work in Canada?",
        [policy],
    )


@pytest.mark.parametrize(
    ("changes", "expected_blocker"),
    [
        ({"is_expired": True}, "policy_expired"),
        ({"confidence": 0.79}, "policy_confidence_low"),
        ({"provenance": "unknown"}, "policy_provenance_unknown"),
        ({"consent_metadata": {}}, "policy_consent_missing"),
        ({"encryption_valid": False}, "policy_encryption_invalid"),
    ],
)
def test_control_policy_blocks_unsafe_vault_records(changes, expected_blocker):
    policy = _policy()
    policy.update(changes)

    result = _resolve(policy)

    _expect(result["matched"] is True, "unsafe policy should still match")
    _expect(result["can_autofill"] is False, "unsafe policy must not autofill")
    _expect(expected_blocker in result["blocker_codes"], "expected blocker must be present")


def test_control_policy_blocks_conflicting_same_scope_records():
    first = _policy(policy_id=1, answer="Yes")
    second = deepcopy(first)
    second.update({"id": 2, "answer_value": "No", "answer_label": "No"})

    result = resolve_control_policy(
        "Are you legally authorized to work in Canada?",
        [first, second],
    )

    _expect(result["matched"] is True, "conflicting policies should match")
    _expect(result["can_autofill"] is False, "conflicting policies must not autofill")
    _expect(result["blocker_codes"] == ["policy_scope_conflict"], "scope conflict must block")
    _expect(set(result["conflict_policy_ids"]) == {1, 2}, "both conflicting policy ids must be returned")


def test_caseware_french_proficiency_maps_to_language_proficiency():
    result = classify_control_question(
        "What is your level of proficiency in French?"
    )

    _expect(result["canonical_key"] == "language_proficiency", "French proficiency must classify correctly")


def test_caseware_post_secondary_education_maps_to_degree_completion():
    result = classify_control_question(
        "Do you have post-secondary education?"
    )

    _expect(result["canonical_key"] == "degree_completion", "education question must classify correctly")


def test_caseware_bilingual_question_stays_official_language_proficiency():
    result = classify_control_question(
        "Are you fluent in both French and English verbally and in writing?"
    )

    _expect(
        result["canonical_key"] == "official_language_proficiency",
        "bilingual question must classify as official language proficiency",
    )


@pytest.mark.parametrize(
    ("descriptor", "expected_key"),
    [
        (
            "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0] | Yes | "
            "Are you physically located in Canada and legally authorized to work in Canada for any employer?",
            "work_authorization",
        ),
        (
            "cards[844edf45-5bb2-4c3e-9b3b-0a0464834f66][field0] | A1 - Beginner | "
            "What is your level of proficiency in French?",
            "language_proficiency",
        ),
        (
            "cards[844edf45-5bb2-4c3e-9b3b-0a0464834f66][field1] | Yes | "
            "Are you fluent in French and English, both verbally and in writing?",
            "official_language_proficiency",
        ),
        (
            "cards[3a847a72-56f8-489d-9daf-269b095ce598][field0] | Yes | "
            "Do you have post-secondary education?",
            "degree_completion",
        ),
    ],
)
def test_caseware_lever_card_descriptor_classifies_from_human_question(descriptor, expected_key):
    result = classify_control_question(descriptor)

    _expect(result["canonical_key"] == expected_key, "Lever card descriptor must classify correctly")


def _exact_policy(question, answer="Yes", key="custom.saved", policy_id=20):
    policy = _policy(policy_id=policy_id, answer=answer)
    policy.update({
        "canonical_key": key,
        "match_phrases": [question],
        "source_metadata": {"question_match_mode": "exact"},
    })
    return policy


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(("saved", "different"), [
    ("What is your gender identity?", "What is your sexual orientation?"),
    ("What is your salary expectation?", "What is your total compensation expectation?"),
    ("What is your salary?", "What is your salary including benefits?"),
    ("你是否愿意出差？", "你是否愿意搬家？"),
])
def test_exact_custom_answers_do_not_cross_question_meanings(saved, different, legacy):
    from app.services.answer_policy import resolve_runtime_policy
    resolver = resolve_runtime_policy if legacy else resolve_control_policy
    policy = _exact_policy(saved)
    _expect(resolver(saved, [policy])["can_autofill"] is True, "exact saved question must autofill")
    _expect(resolver(different, [policy])["matched"] is False, "different question must not match")


def test_exact_custom_question_accepts_formatting_and_explicit_wording_variations():
    policy = _exact_policy("Quel est votre prénom ?", answer="Example")
    policy["match_phrases"].append("What is your first name?")
    for descriptor in ["QUEL EST VOTRE PRÉNOM!", "cards[abc][field0] | Example | What is your first name?"]:
        result = resolve_control_policy(descriptor, [policy])
        _expect(result["can_autofill"] is True, "approved wording variation must autofill")
        _expect(result["answer"] == "Example", "approved wording variation must keep the answer")


def test_custom_unclassified_key_is_not_a_catch_all_policy():
    policy = _exact_policy("Which office would you prefer?", key="custom.unclassified")
    result = resolve_control_policy("Which team would you prefer?", [policy])
    _expect(result["matched"] is False, "unclassified exact policy must not become catch-all")


def test_exact_custom_question_does_not_match_a_lever_answer_option():
    policy = _exact_policy("Yes")
    descriptor = "cards[abc][field0] | Yes | Are you available on weekends?"
    result = resolve_control_policy(descriptor, [policy])
    _expect(result["matched"] is False, "answer option alone must not match exact question policy")


def test_exact_custom_answer_wins_over_broad_catalog_and_legacy_keyword_policy():
    exact = _exact_policy("What is your salary including benefits?", answer="95000 CAD")
    broad = _policy(answer="75000 CAD")
    broad.update({"canonical_key": "salary_expectation"})
    keyword = _policy(answer="80000 CAD")
    keyword.update({"canonical_key": "custom.salary", "match_phrases": ["salary"]})
    result = resolve_control_policy("What is your salary including benefits?", [broad, keyword, exact])
    _expect(result["answer"] == "95000 CAD", "exact custom answer must win over broader policies")
