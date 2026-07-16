from unittest.mock import MagicMock

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.job import Job, JobStatus
from app.models.user import User


def _user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def _approved_job(db_session, suffix: str = "1") -> Job:
    job = Job(
        external_id=f"controller-job-{suffix}",
        title=f"Controller Test Role {suffix}",
        company="Controller Test Company",
        location="Ottawa, Ontario",
        salary_min=70000,
        description="Bilingual English and French analyst role.",
        requirements="English and French",
        url=f"https://boards.greenhouse.io/example/jobs/{suffix}",
        status=JobStatus.approved,
        seniority="mid",
        relevance_score=0.91,
        raw_data={"language": "english", "requires_sponsorship": False},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _stub_tasks(monkeypatch):
    task_result = MagicMock(id="controller-test-task")
    delay = MagicMock(return_value=task_result)
    apply_async = MagicMock(return_value=task_result)
    monkeypatch.setattr("app.api.controller.generate_cover_letter_task.delay", delay)
    monkeypatch.setattr("app.api.controller.submit_application_task.apply_async", apply_async)
    return delay, apply_async


def test_bulk_prepare_is_dry_run_only_and_preserves_job_state(
    auth_client, db_session, monkeypatch
):
    user = _user(db_session)
    job = _approved_job(db_session)
    delay, apply_async = _stub_tasks(monkeypatch)

    response = auth_client.post("/api/controller/bulk-prepare?limit=5&dry_run=false")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["live_submission_enabled_by_controller"] is False
    assert payload["prepared"] == 1
    assert payload["applied"] == 1

    db_session.expire_all()
    stored_job = db_session.query(Job).filter(Job.id == job.id).one()
    application = (
        db_session.query(Application)
        .filter(Application.user_id == user.id, Application.job_id == job.id)
        .one()
    )
    event = (
        db_session.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.event_type == "controller_dry_run_created",
        )
        .one()
    )

    assert stored_job.status == JobStatus.approved
    assert application.status == ApplicationStatus.pending
    assert application.automation_state == ApplicationAutomationState.preparing.value
    assert application.submission_idempotency_key == f"application:{user.id}:job:{job.id}"
    assert event.payload["dry_run"] is True
    assert event.payload["live_submit_requested"] is False
    delay.assert_called_once_with(application.id)
    apply_async.assert_called_once()
    assert apply_async.call_args.kwargs["kwargs"] == {"dry_run": True}


def test_safe_dry_run_ignores_live_submit_query_and_prepares_existing_approved_job(
    auth_client, db_session, monkeypatch
):
    job = _approved_job(db_session, "2")
    _stub_tasks(monkeypatch)

    async def no_new_jobs(**_kwargs):
        return []

    monkeypatch.setattr("app.api.controller.search_jobs", no_new_jobs)

    response = auth_client.post(
        "/api/controller/safe-dry-run?min_score=0.8&daily_limit=2&dry_run=false"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["live_submission_enabled_by_controller"] is False
    assert payload["jobs_found"] == 0
    assert payload["applications_queued"] == 1

    db_session.expire_all()
    stored_job = db_session.query(Job).filter(Job.id == job.id).one()
    application = db_session.query(Application).filter(Application.job_id == job.id).one()
    assert stored_job.status == JobStatus.approved
    assert application.automation_state == ApplicationAutomationState.preparing.value


def test_controller_deduplicates_existing_application(auth_client, db_session, monkeypatch):
    user = _user(db_session)
    job = _approved_job(db_session, "3")
    existing = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key=f"application:{user.id}:job:{job.id}",
    )
    db_session.add(existing)
    db_session.commit()
    delay, apply_async = _stub_tasks(monkeypatch)

    response = auth_client.post("/api/controller/bulk-prepare")

    assert response.status_code == 200
    payload = response.json()
    assert payload["prepared"] == 0
    assert payload["skipped"] == 1
    assert db_session.query(Application).filter(Application.job_id == job.id).count() == 1
    delay.assert_not_called()
    apply_async.assert_not_called()
