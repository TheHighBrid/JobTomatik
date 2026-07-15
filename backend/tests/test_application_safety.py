import pytest

from tests.conftest import TestingSessionLocal
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewTask,
    SubmissionEvidence,
    SubmissionEvidenceType,
)
from app.models.job import Job, JobSource, JobStatus
from app.services.application_state import (
    InvalidApplicationTransition,
    create_manual_review_task,
    record_submission_evidence,
    transition_application_state,
)


def _create_job(*, suffix: str, url: str | None = "https://company.example/apply") -> Job:
    db = TestingSessionLocal()
    job = Job(
        title="Fraud Analyst",
        company="TestCo",
        status=JobStatus.approved,
        source=JobSource.indeed,
        external_id=f"safety-{suffix}",
        relevance_score=0.9,
        url=url,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": url,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.close()
    return job


def test_explicit_idempotency_key_returns_existing_application(auth_client):
    job = _create_job(suffix="idempotency")
    payload = {"job_id": job.id, "idempotency_key": "request-12345678"}

    first = auth_client.post("/api/applications", json=payload)
    second = auth_client.post("/api/applications", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["submission_idempotency_key"] == "request-12345678"


def test_application_creation_records_initial_state_event(auth_client):
    job = _create_job(suffix="initial-event")

    response = auth_client.post("/api/applications", json={"job_id": job.id})

    assert response.status_code == 201
    data = response.json()
    assert data["automation_state"] == ApplicationAutomationState.preparing.value
    assert data["events"][0]["event_type"] == "application_created"
    assert data["events"][0]["to_state"] == ApplicationAutomationState.preparing.value


def test_manual_review_can_be_listed_and_resolved(auth_client):
    job = _create_job(suffix="manual-review")
    app_id = auth_client.post("/api/applications", json={"job_id": job.id}).json()["id"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    review = create_manual_review_task(
        db,
        application,
        ManualReviewReason.ambiguous_question,
        "The employer question needs a user-approved answer.",
        details={"question": "Are you willing to travel?"},
        blocking_url=job.url,
    )
    db.commit()
    review_id = review.id
    db.close()

    listed = auth_client.get(f"/api/applications/{app_id}/manual-reviews")
    assert listed.status_code == 200
    assert listed.json()[0]["reason_code"] == ManualReviewReason.ambiguous_question.value

    resolved = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/resolve",
        json={"resolution_notes": "Answer policy added."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    application_response = auth_client.get(f"/api/applications/{app_id}")
    assert application_response.json()["automation_state"] == ApplicationAutomationState.ready_to_apply.value


def test_submission_evidence_is_exposed(auth_client):
    job = _create_job(suffix="evidence")
    app_id = auth_client.post("/api/applications", json={"job_id": job.id}).json()["id"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    record_submission_evidence(
        db,
        application,
        SubmissionEvidenceType.confirmation_page,
        is_sufficient=True,
        final_url="https://company.example/application/complete",
        confirmation_text="Thank you for applying.",
    )
    db.commit()
    db.close()

    response = auth_client.get(f"/api/applications/{app_id}/evidence")
    assert response.status_code == 200
    assert response.json()[0]["is_sufficient"] is True
    assert response.json()[0]["evidence_type"] == SubmissionEvidenceType.confirmation_page.value


def test_invalid_state_transition_is_rejected(auth_client):
    job = _create_job(suffix="invalid-transition")
    app_id = auth_client.post("/api/applications", json={"job_id": job.id}).json()["id"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    application.automation_state = ApplicationAutomationState.confirmed.value

    with pytest.raises(InvalidApplicationTransition):
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.ready_to_apply,
            "illegal_retry",
        )
    db.rollback()
    db.close()


def test_live_success_without_evidence_becomes_submission_uncertain(auth_client, monkeypatch):
    job = _create_job(suffix="uncertain")
    app_id = auth_client.post(
        "/api/applications",
        json={"job_id": job.id, "cover_letter": "Prepared cover letter"},
    ).json()["id"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    application.automation_state = ApplicationAutomationState.ready_to_apply.value
    application.user.automation_settings = {"auto_followup": False}
    db.commit()
    db.close()

    monkeypatch.setattr("app.tasks.applications.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.tasks.applications.settings.allow_real_application_submit", True)
    monkeypatch.setattr(
        "app.tasks.applications._ensure_application_method",
        lambda current_job: {
            "application_method": "external_url",
            "selected_apply_url": current_job.url,
        },
    )

    async def fake_fill_and_submit_application(**kwargs):
        return {
            "success": True,
            "dry_run": False,
            "url": job.url,
            "application_url": job.url,
            "log": [{"action": "submit_click"}],
            "submitted_at": "2026-07-15T10:00:00",
            "error": None,
            "fields_filled": 4,
            "requires_manual_review": False,
        }

    monkeypatch.setattr(
        "app.tasks.applications.fill_and_submit_application",
        fake_fill_and_submit_application,
    )

    from app.tasks.applications import submit_application_task

    result = submit_application_task.run(app_id, dry_run=False)

    assert result["success"] is False
    assert result["requires_manual_review"] is True

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    assert application.status == ApplicationStatus.pending
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert db.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == app_id,
        ManualReviewTask.reason_code == ManualReviewReason.submission_confirmation_uncertain.value,
    ).count() == 1
    assert db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == app_id).count() == 0
    db.close()
