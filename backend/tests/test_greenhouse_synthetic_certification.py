import json

from app.services.greenhouse_certification import (
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
    assert len(policies) == 3
    assert all(policy["confirmed_at"] for policy in policies)
    assert all(policy["allow_autofill"] is True for policy in policies)

    by_phrase = {policy["match_phrases"][0]: policy for policy in policies}
    assert by_phrase["Will you require sponsorship?"]["answer_label"] == "No"
    assert by_phrase["Why are you interested in this role?"]["answer_label"] == SYNTHETIC_TEXT_RESPONSE
    assert by_phrase["Gender identity"]["answer_label"] == "Prefer not to say"


def test_write_synthetic_resume_creates_valid_pdf(tmp_path):
    target = tmp_path / "synthetic-resume.pdf"
    result = write_synthetic_resume(str(target))

    assert result == str(target)
    assert target.read_bytes().startswith(b"%PDF")
    assert target.stat().st_size > 100
