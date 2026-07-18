import pytest

from app.models.application import Application, ApplicationAutomationState, ApplicationEvent
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.supervised_pilot_intake import (
    SupervisedPilotIntakeError,
    normalize_greenhouse_application_url,
)


CANDIDATE = {
    "employer": "Example Employer",
    "role": "Bilingual Customer Success Manager",
    "application_url": "https://job-boards.greenhouse.io/example/jobs/1234567",
    "location": "Remote, Canada",
    "notes": "User selected this exact role for Phase B preparation.",
    "source_reference": "operator-review-2026-07-18",
}


def test_authenticated_intake_creates_preparation_only_candidate(auth_client, db_session):
    response = auth_client.post("/api/supervised-pilot/candidates", json=CANDIDATE)

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_job"] is True
    assert payload["created_application"] is True
    assert payload["selection_policy"] == "user_selected_exact_application"
    assert payload["automation_state"] == ApplicationAutomationState.preparing.value
    assert payload["submission_queued"] is False
    assert payload["approval_issued"] is False
    assert payload["runtime_flags_changed"] is False

    user = db_session.query(User).filter(User.email == "test@example.com").one()
    job = db_session.query(Job).filter(Job.id == payload["job_id"]).one()
    application = (
        db_session.query(Application)
        .filter(Application.id == payload["application_id"])
        .one()
    )
    event = (
        db_session.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.event_type == "supervised_pilot_candidate_imported",
        )
        .one()
    )

    assert application.user_id == user.id
    assert application.job_id == job.id
    assert application.automation_state == ApplicationAutomationState.preparing.value
    assert application.submission_attempt_count == 0
    assert application.cover_letter is None
    assert application.applied_at is None
    assert job.source == JobSource.manual
    assert job.status == JobStatus.queued
    assert job.raw_data["selection_policy"] == "user_selected_exact_application"
    assert job.raw_data["selected_apply_url"] == CANDIDATE["application_url"]
    assert event.payload["submission_queued"] is False
    assert event.payload["approval_issued"] is False
    assert event.payload["runtime_flags_changed"] is False
    assert len(event.payload["application_url_sha256"]) == 64


def test_intake_is_idempotent_for_same_user_and_exact_target(auth_client, db_session):
    first = auth_client.post("/api/supervised-pilot/candidates", json=CANDIDATE)
    second = auth_client.post("/api/supervised-pilot/candidates", json=CANDIDATE)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["application_id"] == first.json()["application_id"]
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["created_job"] is False
    assert second.json()["created_application"] is False
    assert db_session.query(Job).count() == 1
    assert db_session.query(Application).count() == 1
    assert (
        db_session.query(ApplicationEvent)
        .filter(ApplicationEvent.event_type == "supervised_pilot_candidate_imported")
        .count()
        == 1
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://job-boards.greenhouse.io/example/jobs/123",
        "https://user:pass@job-boards.greenhouse.io/example/jobs/123",
        "https://greenhouse.io.attacker.example/example/jobs/123",
        "https://job-boards.greenhouse.io/example",
        "https://job-boards.greenhouse.io:8443/example/jobs/123",
    ],
)
def test_intake_rejects_unsafe_or_non_exact_targets(auth_client, url):
    response = auth_client.post(
        "/api/supervised-pilot/candidates",
        json={**CANDIDATE, "application_url": url},
    )

    assert response.status_code == 422


def test_intake_rejects_non_greenhouse_platform(auth_client):
    response = auth_client.post(
        "/api/supervised-pilot/candidates",
        json={
            **CANDIDATE,
            "application_url": "https://jobs.lever.co/example/123",
        },
    )

    assert response.status_code == 422
    assert "official greenhouse.io domain" in response.json()["detail"]


def test_intake_endpoint_requires_authentication(client):
    response = client.post("/api/supervised-pilot/candidates", json=CANDIDATE)

    assert response.status_code == 401


def test_greenhouse_embed_and_query_job_urls_are_supported():
    assert normalize_greenhouse_application_url(
        "https://boards.greenhouse.io/embed/job_app?token=abc123#apply"
    ) == "https://boards.greenhouse.io/embed/job_app?token=abc123"
    assert normalize_greenhouse_application_url(
        "https://job-boards.greenhouse.io/example?gh_jid=123456"
    ) == "https://job-boards.greenhouse.io/example?gh_jid=123456"


def test_normalizer_rejects_missing_exact_job_identity():
    with pytest.raises(SupervisedPilotIntakeError, match="one exact Greenhouse job"):
        normalize_greenhouse_application_url(
            "https://job-boards.greenhouse.io/example"
        )
