from app.models.answer_policy import ApplicantAnswerPolicy
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
from tests.conftest import TestingSessionLocal


CASEWARE_URL = "https://jobs.lever.co/caseware/4d0b119c-3cf5-4716-a343-276831f9cc74/apply"


def _work_authorization_question():
    name = "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0]"
    return {
        "reason_code": "ambiguous_question",
        "summary": "Approved answer required for an employer question.",
        "details": {
            "canonical_key": "custom.unclassified",
            "category": "custom",
            "sensitivity": "standard",
            "descriptor": (
                f"{name} | Yes | "
                "Are you physically located in Canada and legally authorized to work in Canada for any employer?"
            ),
            "control_type": "radio",
            "required": True,
            "policy_reason": "No approved answer policy exists for this question.",
            "available_options": [
                {"label": f"{name} | Yes", "value": "Yes", "disabled": False},
                {"label": f"{name} | No", "value": "No", "disabled": False},
            ],
            "control_engine_version": "2.1.0",
        },
    }


def _degree_question():
    name = "cards[3a847a72-56f8-489d-9daf-269b095ce598][field0]"
    return {
        "reason_code": "ambiguous_question",
        "summary": "Approved answer required for an employer question.",
        "details": {
            "canonical_key": "custom.unclassified",
            "descriptor": f"{name} | Yes | Do you have post-secondary education?",
            "control_type": "radio",
            "required": True,
            "available_options": [
                {"label": f"{name} | Yes", "value": "Yes", "disabled": False},
                {"label": f"{name} | No", "value": "No", "disabled": False},
            ],
        },
    }


def _seed_caseware_review(*, question=None, second_review=False):
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
            summary="1 application question(s) require an approved answer policy.",
            blocking_url=CASEWARE_URL,
            details={
                "method": "external_url",
                "questions": [question or _work_authorization_question()],
                "log": [],
            },
        )
        db.add(review)
        db.flush()
        if second_review:
            db.add(ManualReviewTask(
                application_id=app.id,
                reason_code="captcha_detected",
                status=ManualReviewStatus.open.value,
                summary="Employer verification requires owner action.",
                blocking_url=CASEWARE_URL,
                details={"method": "external_url"},
            ))
        db.commit()
        return app.id, review.id, user.id
    finally:
        db.close()


def _create_work_authorization_policy(auth_client, answer="Yes"):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "work_authorization",
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
    assert response.status_code == 201
    return response.json()


def test_policy_revalidation_keeps_review_open_when_answer_is_still_missing(auth_client):
    app_id, review_id, _ = _seed_caseware_review()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is False
    assert data["resolved"] is False
    assert data["satisfied_questions"] == 0
    assert data["total_questions"] == 1
    assert data["remaining"][0]["canonical_key"] == "work_authorization"

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert app.automation_state == ApplicationAutomationState.needs_review.value
        assert app.submission_attempt_count == 0
        assert review.status == ManualReviewStatus.open.value
        assert db.query(SubmissionApproval).filter(SubmissionApproval.application_id == app_id).count() == 0
        assert db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == app_id).count() == 0
    finally:
        db.close()


def test_policy_revalidation_resolves_only_after_exact_retained_option_match(auth_client):
    app_id, review_id, _ = _seed_caseware_review()
    _create_work_authorization_policy(auth_client, "Yes")

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["resolved"] is True
    assert data["remaining"] == []

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert app.automation_state == ApplicationAutomationState.ready_to_apply.value
        assert app.submission_attempt_count == 0
        assert review.status == ManualReviewStatus.resolved.value
        assert "revalidated" in (review.resolution_notes or "").lower()
        assert db.query(SubmissionApproval).filter(SubmissionApproval.application_id == app_id).count() == 0
        assert db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == app_id).count() == 0
    finally:
        db.close()


def test_policy_revalidation_fails_closed_when_answer_does_not_match_retained_options(auth_client):
    app_id, review_id, _ = _seed_caseware_review()
    _create_work_authorization_policy(auth_client, "Maybe")

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["resolved"] is False
    assert data["remaining"][0]["blocker_codes"] == ["retained_option_mismatch"]

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert app.automation_state == ApplicationAutomationState.needs_review.value
        assert review.status == ManualReviewStatus.open.value
    finally:
        db.close()


def test_policy_revalidation_does_not_mark_application_ready_while_another_review_is_open(auth_client):
    app_id, review_id, _ = _seed_caseware_review(second_review=True)
    _create_work_authorization_policy(auth_client, "Yes")

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    assert response.json()["resolved"] is True

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert review.status == ManualReviewStatus.resolved.value
        assert app.automation_state == ApplicationAutomationState.needs_review.value
    finally:
        db.close()


def test_legacy_invalid_degree_policy_remains_blocked_until_owner_reenters_answer(auth_client):
    app_id, review_id, user_id = _seed_caseware_review(question=_degree_question())
    db = TestingSessionLocal()
    try:
        db.add(ApplicantAnswerPolicy(
            user_id=user_id,
            canonical_key="degree_completion",
            category="education",
            sensitivity="standard",
            mode="answer",
            encrypted_value="not-a-valid-fernet-token",
            encrypted_label="not-a-valid-fernet-token",
            encrypted_fallbacks=None,
            match_phrases=[],
            scope="global",
            scope_value="",
            allow_autofill=True,
            is_active=True,
            provenance="user_provided",
            confidence=1.0,
            confirmed_at=__import__("datetime").datetime.utcnow(),
            consent_metadata={"autofill_authorized": True},
        ))
        db.commit()
    finally:
        db.close()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    remaining = response.json()["remaining"]
    assert remaining[0]["canonical_key"] == "degree_completion"
    assert "policy_encryption_invalid" in remaining[0]["blocker_codes"]
    assert "policy_answer_missing" in remaining[0]["blocker_codes"]

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert app.automation_state == ApplicationAutomationState.needs_review.value
        assert review.status == ManualReviewStatus.open.value
    finally:
        db.close()


def test_non_policy_review_cannot_be_retired_by_policy_revalidation(auth_client):
    app_id, _, _ = _seed_caseware_review()
    db = TestingSessionLocal()
    try:
        other = ManualReviewTask(
            application_id=app_id,
            reason_code="captcha_detected",
            status=ManualReviewStatus.open.value,
            summary="Verification required.",
            blocking_url=CASEWARE_URL,
            details={},
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id
    finally:
        db.close()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{other_id}/revalidate-answer-policies"
    )

    assert response.status_code == 409
    assert "not an answer-policy review" in response.json()["detail"]
