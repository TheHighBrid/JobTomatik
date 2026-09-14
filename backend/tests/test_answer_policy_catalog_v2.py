import re

import pytest

from app.services.answer_policy import QUESTION_CATALOG, classify_question
from app.services.control_policy import classify_control_question


def _keys():
    return [item["canonical_key"] for item in QUESTION_CATALOG]


def _item(key):
    return next(item for item in QUESTION_CATALOG if item["canonical_key"] == key)


def test_catalog_v2_is_large_unique_and_regex_valid():
    keys = _keys()
    assert len(keys) == len(set(keys))
    assert len(keys) >= 110

    for item in QUESTION_CATALOG:
        assert item["canonical_key"]
        assert item["patterns"]
        for pattern in item["patterns"]:
            re.compile(pattern, flags=re.IGNORECASE)


def test_catalog_keeps_profile_fields_out_of_answer_policy_vault():
    keys = set(_keys())
    assert {
        "full_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "address",
        "city",
        "postal_code",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        "resume",
    }.isdisjoint(keys)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What is your salary expectation?", "salary_expectation"),
        ("What is your compensation expectation?", "compensation_expectation"),
        ("What is your expected total compensation?", "total_compensation_expectation"),
        ("What is your current salary?", "current_salary"),
        ("What is your current total compensation?", "current_total_compensation"),
        ("What is your expected hourly rate?", "hourly_rate_expectation"),
        ("Does this compensation range align with your expectations?", "compensation_range_acceptance"),
        ("Are you legally authorized to work in Canada?", "work_authorization"),
        ("Do you require employer sponsorship?", "sponsorship_required"),
        ("Will you in the future require visa sponsorship?", "sponsorship_future_required"),
        ("What is your country of citizenship?", "citizenship_status"),
        ("Are you a permanent resident?", "permanent_residency_status"),
        ("What is your current immigration status?", "immigration_status"),
        ("What is your current work permit status?", "work_permit_status"),
        ("What security clearance do you currently hold?", "security_clearance"),
        ("Are you eligible to obtain Secret security clearance?", "security_clearance_eligibility"),
        ("What is your gender identity?", "gender_identity"),
        ("What is your legal sex?", "sex_identity"),
        ("What is your sexual orientation?", "sexual_orientation"),
        ("What is your race?", "race_identity"),
        ("What is your ethnicity?", "ethnicity_identity"),
        ("Please select your race and ethnicity.", "race_ethnicity"),
        ("Are you Hispanic or Latino?", "hispanic_latino_identity"),
        ("Do you have a disability?", "disability_status"),
        ("Do you require an accommodation during the interview?", "accommodation_required"),
        ("Are you able to commute to our Ottawa office?", "commute_ability"),
        ("Are you willing to relocate for this role?", "willing_to_relocate"),
        ("Would you require relocation assistance?", "relocation_assistance"),
        ("Do you have reliable high-speed internet?", "remote_equipment"),
        ("Do you have a dedicated workspace for remote work?", "remote_workspace"),
        ("How many hours per week are you available to work?", "hours_per_week"),
        ("Are you available for an on-call rotation?", "on_call_availability"),
        ("Have you previously applied to our company?", "prior_application"),
        ("Have you previously interviewed with our company?", "prior_interview"),
        ("May we contact your current employer?", "current_employer_contact"),
        ("May we contact your former employers?", "former_employer_contact"),
        ("Do you consent to an employment verification?", "employment_verification_consent"),
        ("Do you consent to an education verification?", "education_verification_consent"),
        ("Are you willing to complete a pre-employment drug screening?", "drug_screening_consent"),
    ],
)
def test_near_neighbor_questions_classify_separately(question, expected):
    assert classify_question(question)["canonical_key"] == expected
    assert classify_control_question(question)["canonical_key"] == expected


@pytest.mark.parametrize(
    "key",
    [
        "skill_experience",
        "skill_years_experience",
        "tool_proficiency",
        "industry_experience",
        "management_experience",
        "management_years",
        "team_size_managed",
        "role_fit",
        "relevant_project",
        "career_goals",
        "strengths",
        "weakness",
        "teamwork_example",
        "leadership_example",
        "conflict_example",
        "difficult_customer_example",
        "deadline_example",
        "failure_learning",
        "feedback_example",
        "initiative_example",
        "process_improvement",
        "problem_solving_example",
    ],
)
def test_dynamic_or_narrative_families_default_to_fresh_review(key):
    assert _item(key)["default_mode"] == "ask_each_time"


def test_skill_subjects_are_not_mistaken_for_salary_or_demographics():
    samples = {
        "How many years of experience do you have with Python?": "skill_years_experience",
        "Do you have experience using Salesforce?": "skill_experience",
        "How proficient are you with Microsoft Excel?": "tool_proficiency",
        "How many years of management experience do you have?": "management_years",
        "What is the largest team you have managed?": "team_size_managed",
    }
    for question, expected in samples.items():
        assert classify_question(question)["canonical_key"] == expected
        assert classify_control_question(question)["canonical_key"] == expected


def test_behavioral_taxonomy_is_distinct():
    samples = {
        "Tell us about a time you handled workplace conflict.": "conflict_example",
        "Tell us about a time you took initiative without being asked.": "initiative_example",
        "Describe a process improvement you implemented.": "process_improvement",
        "Tell us about a time you failed and what you learned.": "failure_learning",
        "Why are you a strong fit for this position?": "role_fit",
    }
    for question, expected in samples.items():
        assert classify_question(question)["canonical_key"] == expected
        assert classify_control_question(question)["canonical_key"] == expected
