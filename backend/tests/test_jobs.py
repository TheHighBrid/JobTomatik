import pytest
from tests.conftest import TestingSessionLocal
from app.models.job import Job, JobStatus, JobSource


def _create_job(auth_client, **kwargs):
    db = TestingSessionLocal()
    job = Job(
        title=kwargs.get("title", "Software Engineer"),
        company=kwargs.get("company", "TestCo"),
        status=JobStatus.queued,
        source=JobSource.indeed,
        external_id=kwargs.get("external_id", "test-001"),
        relevance_score=0.8,
        skills=["Python"],
        tags=["Senior"],
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.close()
    return job


def test_get_queue_empty(auth_client):
    resp = auth_client.get("/api/jobs/queue")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_get_queue_with_jobs(auth_client):
    _create_job(auth_client)
    resp = auth_client.get("/api/jobs/queue")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["jobs"][0]["title"] == "Software Engineer"


def test_approve_job(auth_client):
    job = _create_job(auth_client)
    resp = auth_client.post(f"/api/jobs/{job.id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_reject_job(auth_client):
    job = _create_job(auth_client)
    resp = auth_client.post(f"/api/jobs/{job.id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_reject_removes_from_queue(auth_client):
    job = _create_job(auth_client, external_id="rej-001")
    auth_client.post(f"/api/jobs/{job.id}/reject")
    resp = auth_client.get("/api/jobs/queue")
    assert resp.json()["total"] == 0


def test_get_nonexistent_job(auth_client):
    resp = auth_client.get("/api/jobs/99999")
    assert resp.status_code == 404


def test_jobs_require_auth(client):
    resp = client.get("/api/jobs/queue")
    assert resp.status_code == 401
