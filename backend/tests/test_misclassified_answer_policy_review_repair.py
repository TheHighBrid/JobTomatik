from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job, JobSource
from app.models.user import User
from app.services.manual_review_shape import normalize_misclassified_question_review_items
from tests.conftest import TestingSessionLocal


CASEWARE_URL = "https://jobs.lever.co/caseware/4d0b119c-3cf5-4716-a343-276831f9cc74/apply"


def _legacy_questions():
    descriptors = [
        "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0] | Yes",
        "cards[844edf45-5bb2-4c3e-9b3b-0a0464834f66][field0] | A1 - Beginner",
        "cards[844edf45-5bb2-4c3e-9b3b-0a0464834f66][field1] | Yes",
        "cards[3a847a72-56f8-489d-9daf-269b095ce598][field0] | Yes",
    ]
    return [
        {
            "reason_code": ManualReviewReason.ambiguous_question.value,
            "summary": "Approved answer required for an employer question.",
            "details": {
                "canonical_key": "custom.unclassified",
                "descriptor": descriptor,
                "control_type": "radio",
                "required": True,
                "available_options": [],
            },
        }
        for descriptor in descriptors
    ]


def _seed_review(*, reason_code: str, summary: str, details: dict):
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "test@example.com").one()
        job = Job(
            title="Bilingual Customer Service Representative",
            company="Caseware",
            location="Canada",
            url=CASEWARE_URL,
            source=JobSource.lever,
        )
        db.add(job)
        db.flush()
        app = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.needs_review.value,
            application_target_url=CASEWARE_URL,
            application_target_status="resolved",
            submission_attempt_count=0,
        )
        db.add(app)
        db.flush()
        review = ManualReviewTask(
            application_id=app.id,
            reason_code=reason_code,
            status=ManualReviewStatus.open.value,
            summary=summary,
            details=details,
            blocking_url=CASEWARE_URL,
        )
        db.add(review)
        db.commit()
        db.refresh(app)
        db.refresh(review)
        return app.id, review.id
    finally:
        db.close()


def test_creation_guard_normalizes_only_descriptor_bearing_question_items():
    result = {
        "review_items": [
            {
                "reason_code": ManualReviewReason.operator_final_submit_required.value,
                "summary": "Approved answer required for an employer question.",
                "details": {
                    "descriptor": "cards[x][field0] | Yes | Are you legally authorized to work in Canada?",
                    "control_type": "radio",
                    "required": True,
                },
            },
            {
                "reason_code": ManualReviewReason.operator_final_submit_required.value,
                "summary": "Review the fully filled application and make the final Submit action yourself after exact approval.",
                "details": {
                    "handoff_stage": "operator_final_submit",
                    "operator_final_click_required": True,
                    "automated_submission_authorized": False,
                },
            },
        ]
    }

    changed = normalize_misclassified_question_review_items(result)

    assert changed == 1
    assert result["review_items"][0]["reason_code"] == ManualReviewReason.ambiguous_question.value
    assert result["review_items"][1]["reason_code"] == ManualReviewReason.operator_final_submit_required.value


def test_application_output_exposes_question_bearing_final_reason_as_policy_review(auth_client):
    app_id, review_id = _seed_review(
        reason_code=ManualReviewReason.operator_final_submit_required.value,
        summary="4 application question(s) require an approved answer policy.",
        details={"method": "external_url", "questions": _legacy_questions(), "log": []},
    )

    response = auth_client.get(f"/api/applications/{app_id}")

    assert response.status_code == 200
    review = next(item for item in response.json()["manual_reviews"] if item["id"] == review_id)
    assert review["reason_code"] == ManualReviewReason.ambiguous_question.value
    assert review["summary"] == "4 application question(s) require an approved answer policy."

    db = TestingSessionLocal()
    try:
        stored = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert stored.reason_code == ManualReviewReason.operator_final_submit_required.value
    finally:
        db.close()


def test_revalidation_repairs_stored_reason_before_policy_check(auth_client):
    app_id, review_id = _seed_review(
        reason_code=ManualReviewReason.operator_final_submit_required.value,
        summary="4 application question(s) require an approved answer policy.",
        details={"method": "external_url", "questions": _legacy_questions(), "log": []},
    )

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["resolved"] is False
    assert data["fresh_reprepare_available"] is True
    assert data["total_questions"] == 4

    db = TestingSessionLocal()
    try:
        stored = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        event = (
            db.query(ApplicationEvent)
            .filter(
                ApplicationEvent.application_id == app_id,
                ApplicationEvent.event_type == "misclassified_answer_policy_review_repaired",
            )
            .one()
        )
        assert stored.reason_code == ManualReviewReason.ambiguous_question.value
        assert event.payload["previous_reason_code"] == ManualReviewReason.operator_final_submit_required.value
        assert event.payload["effective_reason_code"] == ManualReviewReason.ambiguous_question.value
        assert event.payload["question_count"] == 4
        assert event.payload["submission_authorized"] is False
    finally:
        db.close()


def test_genuine_final_submit_review_is_not_reclassified(auth_client):
    app_id, review_id = _seed_review(
        reason_code=ManualReviewReason.operator_final_submit_required.value,
        summary="Owner final action required.",
        details={
            "handoff_stage": "operator_final_submit",
            "operator_final_click_required": True,
            "automated_submission_authorized": False,
        },
    )

    response = auth_client.get(f"/api/applications/{app_id}")

    assert response.status_code == 200
    review = next(item for item in response.json()["manual_reviews"] if item["id"] == review_id)
    assert review["reason_code"] == ManualReviewReason.operator_final_submit_required.value
