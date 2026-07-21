from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from app.api import applications as applications_api
from app.api import controller as controller_api
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import (
    HandoffChallengeType,
    HandoffSessionStatus,
    ManualHandoffSession,
)
from app.models.job import Job, JobStatus
from app.models.user import User
from app.tasks import applications as application_tasks


class _VisibleApplicationTask:
    def __init__(self, session_factory, task_id):
        self.session_factory = session_factory
        self.task_id = task_id
        self.seen_application_ids = []

    def _assert_visible(self, application_id):
        with self.session_factory() as verification_db:
            application = verification_db.query(Application).filter(
                Application.id == application_id
            ).first()
            assert application is not None, (
                f"Application {application_id} was dispatched before its database commit"
            )
        self.seen_application_ids.append(application_id)
        return SimpleNamespace(id=f"{self.task_id}-{application_id}")

    def delay(self, application_id, *args, **kwargs):
        return self._assert_visible(application_id)

    def apply_async(self, args=None, kwargs=None, countdown=None):
        del kwargs, countdown
        return self._assert_visible(args[0])


def _current_user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def test_bulk_submit_commits_application_before_dispatch(auth_client, db_session, monkeypatch):
    user = _current_user(db_session)
    job = Job(
        title="Committed Bulk Role",
        company="Committed Bulk Company",
        url="https://example.com/apply/bulk",
        status=JobStatus.approved,
        relevance_score=0.95,
    )
    db_session.add(job)
    db_session.commit()

    session_factory = sessionmaker(bind=db_session.get_bind())
    cover_task = _VisibleApplicationTask(session_factory, "cover")
    submit_task = _VisibleApplicationTask(session_factory, "submit")
    monkeypatch.setattr(applications_api, "generate_cover_letter_task", cover_task)
    monkeypatch.setattr(applications_api, "submit_application_task", submit_task)

    response = auth_client.post(
        "/api/applications/bulk-submit",
        params={"dry_run": True, "limit": 1, "min_score": 0.5},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    application_id = payload["queued"][0]["application_id"]
    assert cover_task.seen_application_ids == [application_id]
    assert submit_task.seen_application_ids == [application_id]

    db_session.expire_all()
    application = db_session.query(Application).filter(
        Application.id == application_id,
        Application.user_id == user.id,
    ).one()
    assert application.job_id == job.id


def test_controller_commits_application_before_dispatch(auth_client, db_session, monkeypatch):
    user = _current_user(db_session)
    job = Job(
        title="Committed Controller Role",
        company="Committed Controller Company",
        url="https://example.com/apply/controller",
        status=JobStatus.approved,
        relevance_score=0.91,
    )
    db_session.add(job)
    db_session.commit()

    session_factory = sessionmaker(bind=db_session.get_bind())
    cover_task = _VisibleApplicationTask(session_factory, "controller-cover")
    submit_task = _VisibleApplicationTask(session_factory, "controller-submit")
    monkeypatch.setattr(controller_api, "generate_cover_letter_task", cover_task)
    monkeypatch.setattr(controller_api, "submit_application_task", submit_task)

    response = auth_client.post("/api/controller/bulk-prepare", params={"limit": 1})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["prepared"] == 1
    application_id = next(
        item["application_id"]
        for item in payload["results"]
        if not item["skipped"]
    )
    assert cover_task.seen_application_ids == [application_id]
    assert submit_task.seen_application_ids == [application_id]

    db_session.expire_all()
    application = db_session.query(Application).filter(
        Application.id == application_id,
        Application.user_id == user.id,
    ).one()
    assert application.job_id == job.id


def test_manual_applied_status_closes_reviews_handoff_and_all_retry_paths(
    auth_client,
    db_session,
    monkeypatch,
):
    user = _current_user(db_session)
    job = Job(
        title="Manual Confirmation Role",
        company="Manual Confirmation Company",
        url="https://boards.greenhouse.io/example/jobs/123",
        status=JobStatus.applied,
        relevance_score=0.9,
    )
    db_session.add(job)
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_idempotency_key=f"manual-confirmation-{user.id}-{job.id}",
    )
    db_session.add(application)
    db_session.flush()

    review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.captcha_detected.value,
        status=ManualReviewStatus.in_progress.value,
        summary="Human verification is required.",
        blocking_url=job.url,
    )
    db_session.add(review)
    db_session.flush()

    handoff = ManualHandoffSession(
        application_id=application.id,
        manual_review_id=review.id,
        user_id=user.id,
        challenge_type=HandoffChallengeType.captcha.value,
        status=HandoffSessionStatus.claimed.value,
        idempotency_key=f"manual-status-handoff-{application.id}",
        resume_token_hash="r" * 64,
        encrypted_resume_token="encrypted-resume-token",
        resume_token_prefix="resume",
        lease_token_hash="l" * 64,
        encrypted_lease_token="encrypted-lease-token",
        lease_expires_at=datetime.utcnow() + timedelta(minutes=5),
        browser_provider="local_cdp",
        browser_node_id="local-node",
        browser_process_id=12345,
        expires_at=datetime.utcnow() + timedelta(minutes=20),
    )
    db_session.add(handoff)
    db_session.commit()

    terminated = []
    monkeypatch.setattr(
        applications_api,
        "terminate_retained_browser",
        lambda session: terminated.append(session.public_id) or True,
    )

    response = auth_client.patch(
        f"/api/applications/{application.id}",
        json={"status": "applied", "notes": "Employer confirmation observed manually."},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == ApplicationStatus.applied.value
    assert payload["automation_state"] == ApplicationAutomationState.submitted.value
    assert payload["applied_at"] is not None
    assert terminated == [handoff.public_id]

    db_session.expire_all()
    updated_review = db_session.query(ManualReviewTask).filter(
        ManualReviewTask.id == review.id
    ).one()
    updated_handoff = db_session.query(ManualHandoffSession).filter(
        ManualHandoffSession.id == handoff.id
    ).one()
    assert updated_review.status == ManualReviewStatus.dismissed.value
    assert updated_handoff.status == HandoffSessionStatus.cancelled.value

    applications_api.submit_application_task.delay.reset_mock()
    retry = auth_client.post(
        f"/api/applications/{application.id}/submit",
        params={"dry_run": True},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "already_submitted"
    applications_api.submit_application_task.delay.assert_not_called()

    stale_worker_result = application_tasks.submit_application_task.run(
        application.id,
        dry_run=True,
    )
    assert stale_worker_result["idempotent"] is True
    assert stale_worker_result["already_submitted"] is True
    assert stale_worker_result["state"] == ApplicationAutomationState.submitted.value

    supervised = auth_client.get(
        f"/api/supervised-submissions/applications/{application.id}/preflight"
    )
    assert supervised.status_code == 409
    assert "already closed" in supervised.json()["detail"].lower()
