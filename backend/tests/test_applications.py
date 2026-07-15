import pytest
from tests.conftest import TestingSessionLocal
from app.models.job import Job, JobStatus, JobSource


def _create_job(status="approved"):
    db = TestingSessionLocal()
    job = Job(
        title="Senior Python Engineer",
        company="TestCo",
        status=getattr(JobStatus, status),
        source=JobSource.indeed,
        external_id=f"app-test-{status}",
        relevance_score=0.85,
        skills=["Python", "FastAPI"],
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.close()
    return job


def test_create_application(auth_client):
    job = _create_job()
    resp = auth_client.post("/api/applications", json={"job_id": job.id})
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_id"] == job.id
    assert data["status"] == "pending"


def test_create_duplicate_application(auth_client):
    job = _create_job()
    auth_client.post("/api/applications", json={"job_id": job.id})
    resp = auth_client.post("/api/applications", json={"job_id": job.id})
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


def test_list_applications(auth_client):
    job = _create_job()
    auth_client.post("/api/applications", json={"job_id": job.id})
    resp = auth_client.get("/api/applications")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_application_stats(auth_client):
    job = _create_job()
    auth_client.post("/api/applications", json={"job_id": job.id})
    resp = auth_client.get("/api/applications/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["pending"] == 1


def test_update_application_status(auth_client):
    job = _create_job()
    create_resp = auth_client.post("/api/applications", json={"job_id": job.id})
    app_id = create_resp.json()["id"]

    resp = auth_client.patch(f"/api/applications/{app_id}", json={"status": "applied"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"


def test_application_not_found(auth_client):
    resp = auth_client.get("/api/applications/99999")
    assert resp.status_code == 404


def test_applications_require_auth(client):
    resp = client.get("/api/applications")
    assert resp.status_code == 401


def test_submit_defaults_to_dry_run(auth_client):
    job = _create_job()
    create_resp = auth_client.post("/api/applications", json={"job_id": job.id})
    app_id = create_resp.json()["id"]

    resp = auth_client.post(f"/api/applications/{app_id}/submit")

    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True


def test_live_submit_is_blocked_when_gate_is_disabled(auth_client, monkeypatch):
    monkeypatch.setattr(
        "app.api.applications.settings.allow_real_application_submit",
        False,
    )
    job = _create_job()
    create_resp = auth_client.post("/api/applications", json={"job_id": job.id})
    app_id = create_resp.json()["id"]

    resp = auth_client.post(f"/api/applications/{app_id}/submit?dry_run=false")

    assert resp.status_code == 409
    assert "Real application submission is disabled" in resp.json()["detail"]


def test_create_followup(auth_client):
    job = _create_job()
    create_resp = auth_client.post("/api/applications", json={"job_id": job.id})
    app_id = create_resp.json()["id"]

    resp = auth_client.post(f"/api/applications/{app_id}/followups", json={
        "scheduled_at": "2026-07-15T10:00:00",
        "subject": "Following up",
        "message": "Hi, just checking in!",
        "recipient_email": "hr@company.com",
    })
    assert resp.status_code == 201
    assert resp.json()["recipient_email"] == "hr@company.com"
    assert resp.json()["status"] == "pending"
