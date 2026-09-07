from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job, JobSource
from app.models.user import User
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
            "reason_code": "ambiguous_question",
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


def _current_question():
    name = "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0]"
    return {
        "reason_code": "ambiguous_question",
        "summary": "Approved answer required for an employer question.",
        "details": {
            "canonical_key": "work_authorization",
            "descriptor": (
                f"{name} | Yes | "
                "Are you physically located in Canada and legally authorized to work in Canada for any employer?"
            ),
            "control_type": "radio",
            "required": True,
            "available_options": [
                {"label": f"{name} | Yes", "value": "Yes", "disabled": False},
                {"label": f"{name} | No", "value": "No", "disabled": False},
            ],
        },
    }


def _seed(*, questions=None):
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "test@example.com").one()
        job = Job(
            title="Client Success Associate (Bilingual, French/English)",
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
            reason_code="ambiguous_question",
            status=ManualReviewStatus.open.value,
            summary="4 application question(s) require an approved answer policy.",
            details={
                "method": "external_url",
                "questions": questions or _legacy_questions(),
                "log": [],
            },
            blocking_url=CASEWARE_URL,
        )
        db.add(review)
        db.commit()
        db.refresh(app)
        db.refresh(review)
        return app.id, review.id
    finally:
        db.close()


def test_caseware_legacy_opaque_review_is_identified_as_reprepare_only(auth_client):
    app_id, review_id = _seed()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["resolved"] is False
    assert data["fresh_reprepare_available"] is True
    assert data["total_questions"] == 4
    assert data["satisfied_questions"] == 0
    assert {
        tuple(item["blocker_codes"])
        for item in data["remaining"]
    } == {("legacy_opaque_lever_descriptor",)}

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert app.automation_state == ApplicationAutomationState.needs_review.value
        assert review.status == ManualReviewStatus.open.value
    finally:
        db.close()


def test_caseware_legacy_review_can_be_retired_only_for_fresh_fill_only_reprepare(auth_client):
    app_id, review_id = _seed()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/retire-stale-for-reprepare"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["retired"] is True
    assert data["fresh_reprepare_required"] is True
    assert data["submission_authorized"] is False
    assert data["application_state"] == ApplicationAutomationState.ready_to_apply.value

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        event = (
            db.query(ApplicationEvent)
            .filter(
                ApplicationEvent.application_id == app_id,
                ApplicationEvent.event_type == "legacy_policy_review_retired_for_fresh_reprepare",
            )
            .one()
        )
        assert app.automation_state == ApplicationAutomationState.ready_to_apply.value
        assert app.submission_attempt_count == 0
        assert review.status == ManualReviewStatus.resolved.value
        assert "No applicant answer was accepted" in (review.resolution_notes or "")
        assert event.payload["fresh_reprepare_required"] is True
        assert event.payload["submission_authorized"] is False
        assert db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == app_id).count() == 0
    finally:
        db.close()


def test_current_human_prompt_review_cannot_use_stale_retirement_shortcut(auth_client):
    app_id, review_id = _seed(questions=[_current_question()])

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/retire-stale-for-reprepare"
    )

    assert response.status_code == 409
    assert "must pass normal policy revalidation" in response.json()["detail"]

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert app.automation_state == ApplicationAutomationState.needs_review.value
        assert review.status == ManualReviewStatus.open.value
    finally:
        db.close()


def test_stale_retirement_is_forbidden_when_submission_evidence_exists(auth_client):
    app_id, review_id = _seed()
    db = TestingSessionLocal()
    try:
        db.add(SubmissionEvidence(
            application_id=app_id,
            evidence_type="confirmation_page",
            is_sufficient=True,
            final_url="https://jobs.lever.co/caseware/example/thanks",
            confirmation_text="Application submitted!",
        ))
        db.commit()
    finally:
        db.close()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/retire-stale-for-reprepare"
    )

    assert response.status_code == 409
    assert "Submission evidence exists" in response.json()["detail"]
