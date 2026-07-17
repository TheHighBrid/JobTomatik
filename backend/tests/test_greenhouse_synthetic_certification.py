import json

from app.services.answer_policy import resolve_runtime_policy
from app.services.control_primitives import OptionRecord, match_answers_to_options
from app.services.greenhouse_certification import (
    SYNTHETIC_LOCATION,
    SYNTHETIC_TEXT_RESPONSE,
    build_synthetic_profile,
    choose_synthetic_answer,
    write_synthetic_resume,
)


def test_synthetic_answer_selection_is_explicit_and_question_aware():
    assert choose_synthetic_answer(
        "Are you legally authorized to work in Canada?",
        ["Yes", "No"],
        multiple=False,
    ) == "Yes"
    assert choose_synthetic_answer(
        "Will you require sponsorship?",
        ["Yes", "No"],
        multiple=False,
    ) == "No"
    assert choose_synthetic_answer(
        "Gender identity",
        ["Woman", "Man", "Prefer not to say"],
        multiple=False,
    ) == "Prefer not to say"
    assert json.loads(choose_synthetic_answer(
        "Which regions interest you?",
        ["Canada", "United States"],
        multiple=True,
    )) == ["Canada"]
    assert choose_synthetic_answer(
        "Location (City)",
        [],
        multiple=False,
    ) == SYNTHETIC_LOCATION
    assert choose_synthetic_answer(
        "Describe your interest",
        [],
        multiple=False,
    ) == SYNTHETIC_TEXT_RESPONSE


def test_build_synthetic_profile_uses_exact_schema_question_phrases():
    profile = build_synthetic_profile({
        "questions": [
            {
                "label": "First Name",
                "required": True,
                "fields": [{"type": "input_text", "name": "first_name"}],
            },
            {
                "label": "Resume/CV",
                "required": True,
                "fields": [{"type": "input_file", "name": "resume"}],
            },
            {
                "label": "Will you require sponsorship?",
                "required": True,
                "fields": [{
                    "type": "multi_value_single_select",
                    "name": "question_1",
                    "values": [
                        {"value": 1, "label": "Yes"},
                        {"value": 2, "label": "No"},
                    ],
                }],
            },
            {
                "label": "Location (City)",
                "required": True,
                "fields": [{"type": "input_text", "name": "location"}],
            },
            {
                "label": "Longitude",
                "required": False,
                "fields": [{"type": "input_hidden", "name": "longitude"}],
            },
            {
                "label": "Latitude",
                "required": False,
                "fields": [{"type": "input_hidden", "name": "latitude"}],
            },
            {
                "label": "Why are you interested in this role?",
                "required": True,
                "fields": [{"type": "textarea", "name": "question_2"}],
            },
        ],
        "demographic_questions": {
            "questions": [{
                "id": 3,
                "label": "Gender identity",
                "required": False,
                "type": "multi_value_single_select",
                "answer_options": [
                    {"id": 1, "label": "Woman"},
                    {"id": 2, "label": "Prefer not to say"},
                ],
            }]
        },
    })

    assert profile["synthetic_certification_only"] is True
    assert profile["email"].endswith("@example.test")
    policies = profile["answer_policies"]
    assert len(policies) == 5
    assert all(policy["confirmed_at"] for policy in policies)
    assert all(policy["allow_autofill"] is True for policy in policies)

    by_phrase = {policy["match_phrases"][0]: policy for policy in policies}
    assert by_phrase["Will you require sponsorship?"]["answer_label"] == "No"
    assert by_phrase["Location (City)"]["answer_label"] == SYNTHETIC_LOCATION
    assert by_phrase["Why are you interested in this role?"]["answer_label"] == SYNTHETIC_TEXT_RESPONSE
    assert by_phrase["Gender identity"]["answer_label"] == "Prefer not to say"
    assert by_phrase["country | off | Country* | Phone"]["answer_label"] == "Canada +1"
    assert "Longitude" not in by_phrase
    assert "Latitude" not in by_phrase
    assert not any(
        policy["canonical_key"] == "data_processing_consent"
        for policy in policies
    )


def test_data_compliance_adds_explicit_synthetic_only_consent_policy():
    profile = build_synthetic_profile({
        "questions": [],
        "data_compliance": [{
            "type": "gdpr",
            "requires_processing_consent": True,
            "requires_retention_consent": True,
            "retention_period": 365,
        }],
    })

    policies = profile["answer_policies"]
    consent = next(
        policy
        for policy in policies
        if policy["canonical_key"] == "data_processing_consent"
    )

    assert profile["synthetic_certification_only"] is True
    assert consent["answer_label"] == "true"
    assert consent["allow_autofill"] is True
    assert consent["confirmed_at"]
    assert consent["scope_value"] == "greenhouse"

    resolved = resolve_runtime_policy(
        "Allow Example to store and process my data for recruiting purposes.",
        policies,
    )
    assert resolved["matched"] is True
    assert resolved["can_autofill"] is True
    assert resolved["answer"] == "true"

    match = match_answers_to_options(
        [resolved["answer"]],
        [OptionRecord(key="consent", label="I agree", value="1")],
        allow_multiple=False,
    )
    assert match.ok is True
    assert [item.key for item in match.matched] == ["consent"]


def test_data_compliance_without_required_consent_adds_no_policy():
    profile = build_synthetic_profile({
        "questions": [],
        "data_compliance": [{
            "type": "gdpr",
            "requires_processing_consent": False,
            "requires_retention_consent": False,
        }],
    })

    assert not any(
        policy["canonical_key"] == "data_processing_consent"
        for policy in profile["answer_policies"]
    )


def test_write_synthetic_resume_creates_valid_pdf(tmp_path):
    target = tmp_path / "synthetic-resume.pdf"
    result = write_synthetic_resume(str(target))

    assert result == str(target)
    assert target.read_bytes().startswith(b"%PDF")
    assert target.stat().st_size > 100
