from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job, JobSource
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.services.answer_policy import classify_question
from app.services.control_policy import classify_control_question
from app.services.manual_review_policy_revalidation import (
    _legacy_opaque_lever_descriptor,
)
from tests.conftest import TestingSessionLocal


MAPLE_URL = "https://jobs.lever.co/getmaple/bc85fe3b-31ab-4e85-a895-9636123ce393/apply"
PROVINCE_NAME = "cards[cf78633b-fdf2-47da-9b47-5204e337dc31][field4]"
SPONSORSHIP_NAME = "cards[cf78633b-fdf2-47da-9b47-5204e337dc31][field3]"
COMPENSATION_NAME = "cards[cf78633b-fdf2-47da-9b47-5204e337dc31][field5]"
PROVINCE_PROMPT = "Which Canadian province are you currently based in?"
SPONSORSHIP_PROMPT = (
    "Will you now or in the future require employer sponsorship (e.g. a work permit or visa) "
    "to work legally in Canada?"
)
COMPENSATION_PROMPT = (
    "This is a full-time position (40–44 hours per week) with an hourly pay range of $19.35 to $20.75. "
    "Does this range align with your expectations? Note: Bilingual (French/English) candidates are "
    "eligible for an additional $2.00 per hour premium."
)


def _maple_questions():
    return [
        {
            "reason_code": "ambiguous_question",
            "summary": "Approved answer required for an employer question.",
            "details": {
                "canonical_key": "custom.unclassified",
                "descriptor": f"{PROVINCE_NAME} | Type your response | {PROVINCE_PROMPT} *",
                "control_type": "text",
                "required": True,
                "available_options": [],
                "control_engine_version": "2.1.0",
            },
        },
        {
            "reason_code": "legal_answer_missing",
            "summary": "Approved legal answer required for an employer question.",
            "details": {
                "canonical_key": "custom.unclassified",
                "descriptor": f"{SPONSORSHIP_NAME} | {SPONSORSHIP_PROMPT} *",
                "control_type": "select",
                "required": True,
                "available_options": [
                    {"label": "Yes", "value": "Yes", "disabled": False},
                    {"label": "No", "value": "No", "disabled": False},
                ],
                "control_engine_version": "2.1.0",
            },
        },
    ]


def _seed_maple_review():
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "test@example.com").one()
        job = Job(
            title="Bilingual Lab and Referral Operations Coordinators (French/English)",
            company="Maple",
            location="Toronto, Ontario",
            url=MAPLE_URL,
            source=JobSource.lever,
        )
        db.add(job)
        db.flush()
        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.needs_review.value,
            application_target_url=MAPLE_URL,
            application_target_status="resolved",
            submission_attempt_count=0,
        )
        db.add(application)
        db.flush()
        review = ManualReviewTask(
            application_id=application.id,
            reason_code="ambiguous_question",
            status=ManualReviewStatus.open.value,
            summary="2 application question(s) require an approved answer policy.",
            blocking_url=MAPLE_URL,
            details={
                "method": "external_url",
                "questions": _maple_questions(),
                "log": [],
            },
        )
        db.add(review)
        db.commit()
        return application.id, review.id
    finally:
        db.close()


def _create_policy(auth_client, canonical_key, answer):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": canonical_key,
            "mode": "answer",
            "answer_value": answer,
            "answer_label": answer,
            "scope": "global",
            "scope_value": "",
            "allow_autofill": True,
            "confirmed": True,
            "is_active": True,
            "provenance": "user_provided",
            "confidence": 1.0,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_maple_259_readable_two_part_sponsorship_descriptor_is_not_legacy():
    descriptor = f"{SPONSORSHIP_NAME} | {SPONSORSHIP_PROMPT} *"
    assert _legacy_opaque_lever_descriptor(descriptor) is False

    assert _legacy_opaque_lever_descriptor(f"{SPONSORSHIP_NAME} | Yes") is True
    assert _legacy_opaque_lever_descriptor(f"{SPONSORSHIP_NAME} | A1 - Beginner") is True
    assert _legacy_opaque_lever_descriptor(f"{SPONSORSHIP_NAME} | Type your response") is True


def test_maple_259_current_runtime_classifier_distinguishes_all_three_owner_questions():
    province = classify_control_question(
        f"{PROVINCE_NAME} | Type your response | {PROVINCE_PROMPT} *"
    )
    sponsorship = classify_control_question(
        f"{SPONSORSHIP_NAME} | {SPONSORSHIP_PROMPT} *"
    )
    compensation = classify_control_question(
        f"{COMPENSATION_NAME} | {COMPENSATION_PROMPT} *"
    )

    assert province["canonical_key"] == "current_canadian_province"
    assert province["sensitivity"] == "standard"
    assert sponsorship["canonical_key"] == "sponsorship_required"
    assert sponsorship["sensitivity"] == "legal"
    assert compensation["canonical_key"] == "compensation_range_acceptance"
    assert compensation["sensitivity"] == "sensitive"


def test_maple_259_shared_catalog_exposes_province_policy_family():
    classification = classify_question(
        f"{PROVINCE_NAME} | Type your response | {PROVINCE_PROMPT} *"
    )
    assert classification["canonical_key"] == "current_canadian_province"
    assert classification["sensitivity"] == "standard"


def test_maple_259_retained_review_revalidates_without_stale_retirement_or_submission(auth_client):
    application_id, review_id = _seed_maple_review()
    _create_policy(auth_client, "current_canadian_province", "Ontario")
    _create_policy(auth_client, "sponsorship_required", "Yes")

    response = auth_client.post(
        f"/api/applications/{application_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ready"] is True, data
    assert data["resolved"] is True, data
    assert data["satisfied_questions"] == 2, data
    assert data["total_questions"] == 2, data
    assert data["remaining"] == [], data
    assert data["fresh_reprepare_available"] is False, data

    db = TestingSessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert application.automation_state == ApplicationAutomationState.ready_to_apply.value
        assert application.submission_attempt_count == 0
        assert review.status == ManualReviewStatus.resolved.value
        assert db.query(SubmissionApproval).filter(
            SubmissionApproval.application_id == application_id
        ).count() == 0
        assert db.query(SubmissionEvidence).filter(
            SubmissionEvidence.application_id == application_id
        ).count() == 0
    finally:
        db.close()
