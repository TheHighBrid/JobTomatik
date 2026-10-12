"""JT5 status endpoint and isolation from supervised worker wrappers."""
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.submission_integrity import (
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
)
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.tasks.jt5_execution import execute_reserved_application


def _application(db, user, *,
                 state=ApplicationAutomationState.ready_to_apply.value):
    job = Job(
        title="Status Role",
        company="Status Co",
        url="https://boards.greenhouse.io/example/jobs/status",
        source=JobSource.greenhouse,
        status=JobStatus.approved,
        raw_data={},
    )
    db.add(job)
    db.flush()
    item = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=state,
        source_listing_url=job.url,
        application_target_url=job.url,
        submission_idempotency_key=f"jt5-status:{user.id}:{job.id}:{state}",
        cover_letter="Reviewed",
    )
    db.add(item)
    db.flush()
    claim_submission_identity_aliases(
        db,
        item,
        build_submission_identity_aliases(job, application=item),
    )
    return item


def test_status_endpoint_reports_latest_attempt(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _application(db_session, user)
    db_session.commit()

    empty = auth_client.get(f"/api/applications/{application.id}/jt5/status")
    assert empty.status_code == 200
    assert empty.json()["latest_attempt"] is None
    assert empty.json()["execution_contract"] == "jt5"
    assert empty.json()["automatic_retry_allowed"] is False

    _, reserved = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    db_session.commit()

    status = auth_client.get(f"/api/applications/{application.id}/jt5/status")
    body = status.json()
    assert status.status_code == 200
    assert body["latest_attempt"]["reference"] == reserved.reference
    assert body["latest_attempt"]["status"] == "queued"
    assert body["latest_attempt"]["execution_contract"] == "jt5"


def test_status_endpoint_hides_other_users_application(auth_client, db_session):
    other = User(
        email="other-jt5@example.com",
        hashed_password="x",
        full_name="Other",
    )
    db_session.add(other)
    db_session.flush()
    application = _application(db_session, other)
    db_session.commit()

    response = auth_client.get(f"/api/applications/{application.id}/jt5/status")
    assert response.status_code == 404


def test_supervised_gate_does_not_wrap_jt5_task():
    from app.tasks import applications as application_tasks
    from app.services.supervised_submission_integration import (
        install_supervised_submission_task_gate,
    )

    install_supervised_submission_task_gate()
    # Supervised gate mutates submit_application_task.run only.
    assert application_tasks.submit_application_task.run is not None
    # JT5 remains the unbound Celery task function body (no .run monkeypatch required).
    assert execute_reserved_application.name == (
        "app.tasks.jt5_execution.execute_reserved_application"
    )
    assert execute_reserved_application.name != application_tasks.submit_application_task.name


def test_worker_skips_browser_when_application_already_closed(monkeypatch, db_session):
    user = User(
        email="jt5-closed@example.com",
        hashed_password="x",
        full_name="Closed",
    )
    db_session.add(user)
    db_session.flush()
    application = _application(
        db_session,
        user,
        state=ApplicationAutomationState.ready_to_apply.value,
    )
    _, attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    # Simulate concurrent owner/employer close after reserve, before worker claim.
    application.status = ApplicationStatus.applied
    application.automation_state = ApplicationAutomationState.confirmed.value
    db_session.commit()
    reference = attempt.reference

    called = {"browser": False}

    async def fake_fill(*args, **kwargs):
        called["browser"] = True
        return {"success": True}

    monkeypatch.setattr(
        "app.tasks.jt5_execution.fill_and_submit_application",
        fake_fill,
    )

    result = execute_reserved_application.run(application.id, reference)
    assert result["already_submitted"] is True
    assert result["outcome"] == "confirmed"
    assert called["browser"] is False
