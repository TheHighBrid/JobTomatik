"""Execute committed-checkpoint failures without employer or broker requests."""

from unittest.mock import Mock

import pytest
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.user import User
from app.services import (
    application_target_task_integration,
    supervised_submission_integration,
)
from app.tasks import applications
from celery.exceptions import Retry

from tests.conftest import TestingSessionLocal


@pytest.fixture
def task_case(db_session, monkeypatch):
    user = User(email="task-recovery@example.test", hashed_password="synthetic")
    job = Job(
        external_id="task-recovery",
        title="Analyst",
        company="Synthetic",
        url="https://employer.example.test/apply",
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_attempt_count=0,
        submission_idempotency_key="task-recovery",
    )
    db_session.add(application)
    db_session.commit()
    monkeypatch.setattr(applications, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(applications, "_profile_dict", lambda *_: {})
    monkeypatch.setattr(
        applications,
        "_ensure_application_method",
        lambda job: {
            "application_method": "external_url",
            "selected_apply_url": job.url,
        },
    )
    retry = Mock(side_effect=Retry("synthetic retry"))
    monkeypatch.setattr(applications.submit_application_task, "retry", retry)
    return application, retry


def _run(application_id, *, dry_run=True):
    # Exercise the real inner task while leaving live approval wrappers untouched.
    return supervised_submission_integration._ORIGINAL_RUN(
        application_id, dry_run=dry_run
    )


def test_failed_dry_run_recovers_then_retry_reaches_filler(
    task_case, db_session, monkeypatch
):
    application, retry = task_case
    calls = []

    async def fill(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("CDP interrupted before fill")
        return {"success": True, "dry_run": True, "fields_filled": 4, "log": []}

    monkeypatch.setattr(applications, "fill_and_submit_application", fill)
    with pytest.raises(Retry):
        _run(application.id)
    db_session.refresh(application)
    assert application.automation_state == "ready_to_apply"
    assert application.status == ApplicationStatus.pending
    assert application.submission_attempt_count == 1
    assert retry.call_args.kwargs["countdown"] == 5
    assert db_session.query(ManualReviewTask).count() == 0

    result = _run(application.id)
    db_session.refresh(application)
    assert result["success"] is True
    assert result["fields_filled"] == 4
    assert len(calls) == 2
    assert all(call["dry_run"] is True for call in calls)
    assert application.automation_state == "ready_to_apply"
    assert application.submission_attempt_count == 2
    assert application.submission_idempotency_key == "task-recovery"
    assert application.applied_at is None


def test_live_failure_is_uncertain_and_never_retried(
    task_case, db_session, monkeypatch
):
    application, retry = task_case
    monkeypatch.setattr(applications.settings, "allow_real_application_submit", True)

    async def fill(**kwargs):
        raise RuntimeError("unknown employer outcome")

    monkeypatch.setattr(applications, "fill_and_submit_application", fill)
    result = _run(application.id, dry_run=False)
    db_session.refresh(application)
    assert result["success"] is False
    assert result["requires_manual_review"] is True
    assert application.automation_state == "submission_uncertain"
    retry.assert_not_called()


def test_duplicate_task_leaves_active_attempt_alone(task_case, db_session, monkeypatch):
    application, retry = task_case
    application.automation_state = "applying"
    application.status = ApplicationStatus.applying
    application.submission_attempt_count = 7
    db_session.commit()
    fill = Mock(side_effect=AssertionError("must not open another page"))
    monkeypatch.setattr(applications, "fill_and_submit_application", fill)
    result = _run(application.id)
    db_session.refresh(application)
    assert result["idempotent"] is True
    assert application.automation_state == "applying"
    assert application.submission_attempt_count == 7
    fill.assert_not_called()
    retry.assert_not_called()


def test_exception_before_checkpoint_cannot_reset_another_worker(
    task_case, db_session, monkeypatch
):
    application, retry = task_case
    application.automation_state = "applying"
    application.status = ApplicationStatus.applying
    application.submission_attempt_count = 1
    db_session.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="application_attempt_started",
            from_state="ready_to_apply",
            to_state="applying",
            payload={"dry_run": True, "attempt": 1},
        )
    )
    db_session.commit()
    task_db = TestingSessionLocal()
    query = task_db.query
    first = True

    def fail_first_query(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            raise RuntimeError("database temporarily unavailable")
        return query(*args, **kwargs)

    monkeypatch.setattr(task_db, "query", fail_first_query)
    monkeypatch.setattr(applications, "SessionLocal", lambda: task_db)
    with pytest.raises(Retry):
        application_target_task_integration._ORIGINAL_RUN(application.id, dry_run=True)
    db_session.refresh(application)
    assert application.automation_state == "applying"
    assert application.submission_attempt_count == 1
    assert (
        db_session.query(ApplicationEvent)
        .filter_by(
            event_type="runtime_interrupted_application_attempt_recovered",
        )
        .count()
        == 0
    )
    assert retry.call_args.kwargs["countdown"] == 60


def test_late_exception_cannot_reset_newer_attempt(task_case, db_session, monkeypatch):
    application, _ = task_case

    async def fill(**kwargs):
        with TestingSessionLocal() as other_db:
            current = other_db.get(Application, application.id)
            current.submission_attempt_count = 2
            other_db.add(
                ApplicationEvent(
                    application_id=current.id,
                    event_type="application_attempt_started",
                    from_state="ready_to_apply",
                    to_state="applying",
                    payload={"dry_run": True, "attempt": 2},
                )
            )
            other_db.commit()
        raise RuntimeError("late response from previous attempt")

    monkeypatch.setattr(applications, "fill_and_submit_application", fill)
    with pytest.raises(Retry):
        _run(application.id)
    db_session.refresh(application)
    assert application.automation_state == "applying"
    assert application.submission_attempt_count == 2
    assert (
        db_session.query(ApplicationEvent)
        .filter_by(
            event_type="runtime_interrupted_application_attempt_recovered",
        )
        .count()
        == 0
    )


def test_operator_prepare_retry_preserves_fill_only_scope(
    task_case, db_session, monkeypatch
):
    from app.services.operator_assisted_handoff_integration import (
        current_operator_prepare_target,
    )
    from app.tasks import operator_assisted

    application, _ = task_case
    metadata = {"platform": "lever", "target_url": application.job.url}
    calls = []
    states = []

    async def resolve(_job):
        return metadata

    def preflight(_db, current, *_args, **_kwargs):
        states.append(current.automation_state)
        return {"ready": current.automation_state == "ready_to_apply", "blockers": []}

    async def fill(**kwargs):
        calls.append((kwargs["dry_run"], current_operator_prepare_target()))
        if len(calls) == 1:
            raise RuntimeError("temporary browser disconnect")
        return {"success": True, "dry_run": True, "fields_filled": 4, "log": []}

    monkeypatch.setattr(operator_assisted, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        operator_assisted, "resolve_supervised_target_metadata", resolve
    )
    monkeypatch.setattr(
        operator_assisted, "persist_supervised_target_metadata", lambda *_: None
    )
    monkeypatch.setattr(
        operator_assisted, "build_operator_assisted_preflight", preflight
    )
    monkeypatch.setattr(applications, "fill_and_submit_application", fill)
    retry = Mock(side_effect=Retry("operator retry"))
    task = operator_assisted.prepare_operator_assisted_application_task
    monkeypatch.setattr(task, "retry", retry)

    with pytest.raises(Retry):
        task.run(application.id)
    db_session.refresh(application)
    assert application.automation_state == "ready_to_apply"
    retry.assert_called_once()
    assert current_operator_prepare_target() is None

    result = task.run(application.id)
    assert result["success"] is True
    assert result["operator_assisted"] is True
    assert result["automated_submission_authorized"] is False
    assert result["final_submit_clicked_by_jobtomatik"] is False
    assert states == ["ready_to_apply", "ready_to_apply"]
    assert calls == [(True, metadata), (True, metadata)]
    assert current_operator_prepare_target() is None
