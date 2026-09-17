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


def _expect(condition, message):
    if not condition:
        raise AssertionError(message)


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


def _work_arrangement_question(wording):
    return {
        "reason_code": "ambiguous_question",
        "details": {
            "canonical_key": "custom.unclassified",
            "descriptor": f"cards[custom-card][field0] | Hybrid | {wording}",
            "control_type": "radio",
            "required": True,
            "available_options": [
                {"label": "Hybrid", "value": "hybrid"},
                {"label": "Remote", "value": "remote"},
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
    _expect(response.status_code == 201, "policy creation must return 201")
    return response.json()


def test_policy_revalidation_keeps_review_open_when_answer_is_still_missing(auth_client):
    app_id, review_id, _ = _seed_caseware_review()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    _expect(response.status_code == 200, "revalidation must return 200")
    data = response.json()
    _expect(data["ready"] is False, "missing policy must not be ready")
    _expect(data["resolved"] is False, "missing policy must stay unresolved")
    _expect(data["satisfied_questions"] == 0, "no question should be satisfied")
    _expect(data["total_questions"] == 1, "one question should be evaluated")
    _expect(data["remaining"][0]["canonical_key"] == "work_authorization", "work authorization must remain")

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        _expect(app.automation_state == ApplicationAutomationState.needs_review.value, "application must remain in review")
        _expect(app.submission_attempt_count == 0, "revalidation must not submit")
        _expect(review.status == ManualReviewStatus.open.value, "review must remain open")
        _expect(db.query(SubmissionApproval).filter(SubmissionApproval.application_id == app_id).count() == 0, "revalidation must not create approval")
        _expect(db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == app_id).count() == 0, "revalidation must not create evidence")
    finally:
        db.close()


def test_policy_revalidation_resolves_only_after_exact_retained_option_match(auth_client):
    app_id, review_id, _ = _seed_caseware_review()
    _create_work_authorization_policy(auth_client, "Yes")

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    _expect(response.status_code == 200, "revalidation must return 200")
    data = response.json()
    _expect(data["ready"] is True, "matching policy must be ready")
    _expect(data["resolved"] is True, "matching policy must resolve")
    _expect(data["remaining"] == [], "matching policy must leave no remaining questions")

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        _expect(app.automation_state == ApplicationAutomationState.ready_to_apply.value, "application must become ready")
        _expect(app.submission_attempt_count == 0, "revalidation must not submit")
        _expect(review.status == ManualReviewStatus.resolved.value, "review must resolve")
        _expect("revalidated" in (review.resolution_notes or "").lower(), "resolution notes must record revalidation")
        _expect(db.query(SubmissionApproval).filter(SubmissionApproval.application_id == app_id).count() == 0, "revalidation must not create approval")
        _expect(db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == app_id).count() == 0, "revalidation must not create evidence")
    finally:
        db.close()


def test_policy_revalidation_fails_closed_when_answer_does_not_match_retained_options(auth_client):
    app_id, review_id, _ = _seed_caseware_review()
    _create_work_authorization_policy(auth_client, "Maybe")

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    _expect(response.status_code == 200, "revalidation must return 200")
    data = response.json()
    _expect(data["resolved"] is False, "mismatched option must stay unresolved")
    _expect(data["remaining"][0]["blocker_codes"] == ["retained_option_mismatch"], "retained option mismatch must block")

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        _expect(app.automation_state == ApplicationAutomationState.needs_review.value, "application must remain in review")
        _expect(review.status == ManualReviewStatus.open.value, "review must remain open")
    finally:
        db.close()


def test_policy_revalidation_does_not_mark_application_ready_while_another_review_is_open(auth_client):
    app_id, review_id, _ = _seed_caseware_review(second_review=True)
    _create_work_authorization_policy(auth_client, "Yes")

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    _expect(response.status_code == 200, "revalidation must return 200")
    _expect(response.json()["resolved"] is True, "answer-policy review should resolve")

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        _expect(review.status == ManualReviewStatus.resolved.value, "answer-policy review must resolve")
        _expect(app.automation_state == ApplicationAutomationState.needs_review.value, "other review must keep application blocked")
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

    _expect(response.status_code == 200, "revalidation must return 200")
    remaining = response.json()["remaining"]
    _expect(remaining[0]["canonical_key"] == "degree_completion", "degree completion must remain")
    _expect("policy_encryption_invalid" in remaining[0]["blocker_codes"], "invalid encryption must block")
    _expect("policy_answer_missing" in remaining[0]["blocker_codes"], "missing answer must block")

    db = TestingSessionLocal()
    try:
        app = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        _expect(app.automation_state == ApplicationAutomationState.needs_review.value, "application must remain in review")
        _expect(review.status == ManualReviewStatus.open.value, "review must remain open")
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

    _expect(response.status_code == 409, "non-policy review must return 409")
    _expect("not an answer-policy review" in response.json()["detail"], "response must explain wrong review type")


def test_unknown_question_can_be_saved_edited_and_reused_on_recheck(auth_client):
    wording = "Which work arrangement do you prefer?"
    question = _work_arrangement_question(wording)
    app_id, review_id, _ = _seed_caseware_review(question=question)
    url = f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    missing = auth_client.post(url).json()
    _expect(missing["resolved"] is False, "unknown question must start unresolved")
    _expect(missing["remaining"][0]["available_options"][0]["label"] == "Hybrid", "retained options must include Hybrid")
    payload = {
        "canonical_key": "custom.work_arrangement", "match_phrases": [wording],
        "answer_value": "hybrid", "mode": "answer", "scope": "company",
        "scope_value": "Other employer", "allow_autofill": True, "confirmed": True,
        "source_metadata": {"question_match_mode": "exact"},
    }
    saved = auth_client.post("/api/profile/answer-policies", json=payload)
    _expect(saved.status_code == 201, "custom policy creation must return 201")
    policy_id = saved.json()["id"]
    _expect(auth_client.post(url).json()["resolved"] is False, "wrong company scope must not resolve")
    updated = auth_client.patch(f"/api/profile/answer-policies/{policy_id}", json={
        "scope_value": "Caseware", "allow_autofill": False, "confirmed": False,
    })
    _expect(updated.status_code == 200, "policy scope update must return 200")
    _expect(auth_client.post(url).json()["resolved"] is False, "unauthorized policy must remain unresolved")
    approved = auth_client.patch(f"/api/profile/answer-policies/{policy_id}", json={
        "answer_value": "remote", "answer_label": "Remote",
        "allow_autofill": True, "confirmed": True,
    })
    _expect(approved.status_code == 200, "policy approval must return 200")
    result = auth_client.post(url).json()
    _expect(result["resolved"] is True, "approved exact policy must resolve")
    _expect(result["remaining"] == [], "approved exact policy must clear remaining questions")
    next_app, next_review, _ = _seed_caseware_review(question=question)
    again = auth_client.post(f"/api/applications/{next_app}/manual-reviews/{next_review}/revalidate-answer-policies")
    _expect(again.json()["resolved"] is True, "subsequent matching application must reuse the saved answer")
    db = TestingSessionLocal()
    try:
        _expect(db.query(SubmissionApproval).count() == 0, "recheck flow must not create submission approval")
        _expect(db.query(SubmissionEvidence).count() == 0, "recheck flow must not create submission evidence")
        _expect(db.query(Application).filter(Application.id.in_([app_id, next_app])).count() == 2, "both applications must remain present")
    finally:
        db.close()
