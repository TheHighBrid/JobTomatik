from __future__ import annotations

from pathlib import Path

from app.models.application import Application, ApplicationAutomationState, ApplicationStatus, SubmissionEvidence
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.onehost_resilience import (
    recover_after_api_restart,
    recover_after_browser_crash,
    recover_after_confirmation_crash,
    recover_after_redis_loss,
    recover_after_worker_restart,
)
from tests.conftest import TestingSessionLocal


def _application():
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    job = Job(
        external_id="onehost-resilience",
        title="Reliability Analyst",
        company="OneHost",
        url="https://job-boards.greenhouse.io/example/jobs/123",
        source=JobSource.manual,
        status=JobStatus.approved,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_idempotency_key="onehost-resilience-1",
    )
    db.add(application)
    db.commit()
    application_id = application.id
    db.close()
    return application_id


def test_api_restart_preserves_state(auth_client):
    application_id = _application()
    db = TestingSessionLocal()
    result = recover_after_api_restart(db, application_id)
    db.commit()
    db.close()
    reopened = TestingSessionLocal()
    row = reopened.query(Application).filter(Application.id == application_id).one()
    reopened.close()
    assert result["state_preserved"] is True
    assert result["submit_attempted"] is False
    assert row.automation_state == "applying"


def test_worker_restart_does_not_duplicate(auth_client):
    application_id = _application()
    db = TestingSessionLocal()
    before = db.query(Application).count()
    result = recover_after_worker_restart(db, application_id, approval_consumed=True)
    db.commit()
    after = db.query(Application).count()
    db.close()
    assert result["duplicate_application"] is False
    assert result["automation_state"] == "submission_uncertain"
    assert after == before


def test_browser_crash_stays_truthful(auth_client):
    application_id = _application()
    db = TestingSessionLocal()
    result = recover_after_browser_crash(db, application_id)
    db.commit()
    db.close()
    assert result["confirmed"] is False
    assert result["automation_state"] == "submission_uncertain"


def test_redis_loss_creates_no_phantom_submission(auth_client):
    application_id = _application()
    db = TestingSessionLocal()
    result = recover_after_redis_loss(db, application_id, queued_task_id="task-1")
    db.commit()
    status = db.query(Application).filter(Application.id == application_id).one().status
    db.close()
    assert result["phantom_submission"] is False
    assert status == ApplicationStatus.applying


def test_crash_after_confirmation_reconciles(auth_client):
    application_id = _application()
    db = TestingSessionLocal()
    db.add(
        SubmissionEvidence(
            application_id=application_id,
            evidence_type="confirmation_page",
            is_sufficient=True,
            final_url="https://job-boards.greenhouse.io/example/jobs/123/confirmation",
            confirmation_text="Application submitted!",
        )
    )
    db.commit()
    result = recover_after_confirmation_crash(db, application_id)
    db.commit()
    db.close()
    assert result["confirmed"] is True
    assert result["submit_attempted"] is False


def test_production_compose_has_restart_and_health_probes():
    compose = Path(__file__).resolve().parents[2] / "docker-compose.onehost-production.yml"
    text = compose.read_text(encoding="utf-8")
    assert text.count("restart: unless-stopped") >= 4
    assert "pg_isready" in text
    assert "redis-cli" in text
    assert "/api/system/ready" in text
    assert "onehost_state:/state" in text
    assert "onehost_postgres:/var/lib/postgresql/data" in text
