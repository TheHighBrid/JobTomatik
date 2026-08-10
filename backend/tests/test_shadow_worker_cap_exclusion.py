from datetime import datetime
from types import SimpleNamespace

from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.services import operations_policy


NOW = datetime(2026, 8, 10, 4, 0, 0)


def _install_single_application_caps(monkeypatch):
    monkeypatch.setattr(
        operations_policy,
        "get_operations_settings",
        lambda: SimpleNamespace(
            global_kill_switch=False,
            autopilot_enabled=True,
            default_daily_cap=1,
            default_weekly_cap=1,
            quiet_hours_start_utc=0,
            quiet_hours_end_utc=0,
            failure_threshold=5,
            failure_window_minutes=60,
            circuit_breaker_minutes=120,
            disabled_platforms="",
        ),
    )


def _user(db_session, email: str):
    user = User(
        email=email,
        hashed_password="test-hash",
        automation_settings={
            "auto_apply_daily_limit": 1,
            "auto_apply_weekly_limit": 1,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
        },
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _job(db_session, external_id: str, company: str):
    job = Job(
        external_id=external_id,
        title="Risk analyst",
        company=company,
        url=f"https://jobs.lever.co/{external_id}/role",
    )
    db_session.add(job)
    db_session.flush()
    return job


def test_worker_recheck_excludes_current_application_from_global_caps(
    db_session,
    monkeypatch,
):
    _install_single_application_caps(monkeypatch)
    user = _user(db_session, "worker-cap@example.test")
    job = _job(db_session, "worker-cap", "Current Employer")
    app = Application(
        user_id=user.id,
        job_id=job.id,
        submission_idempotency_key=f"application:{user.id}:job:{job.id}",
        created_at=NOW,
    )
    db_session.add(app)
    db_session.flush()

    scheduler_view = operations_policy.evaluate_autopilot_policy(db_session, user, NOW)
    assert scheduler_view.allowed is False
    assert scheduler_view.code == "application_cap_reached"
    assert scheduler_view.metadata["daily_count"] == 1
    assert scheduler_view.metadata["weekly_count"] == 1

    worker_view = operations_policy.evaluate_autopilot_policy(
        db_session,
        user,
        NOW,
        exclude_application_id=app.id,
    )
    assert worker_view.allowed is True
    assert worker_view.code == "autopilot_allowed"
    assert worker_view.metadata["daily_count"] == 0
    assert worker_view.metadata["weekly_count"] == 0
    assert worker_view.metadata["excluded_application_id"] == app.id


def test_worker_cap_exclusion_never_hides_other_applications(
    db_session,
    monkeypatch,
):
    _install_single_application_caps(monkeypatch)
    user = _user(db_session, "worker-cap-other@example.test")
    old_job = _job(db_session, "existing-cap", "Existing Employer")
    current_job = _job(db_session, "current-cap", "Current Employer")
    existing = Application(
        user_id=user.id,
        job_id=old_job.id,
        submission_idempotency_key=f"application:{user.id}:job:{old_job.id}",
        created_at=NOW,
    )
    current = Application(
        user_id=user.id,
        job_id=current_job.id,
        submission_idempotency_key=f"application:{user.id}:job:{current_job.id}",
        created_at=NOW,
    )
    db_session.add_all([existing, current])
    db_session.flush()

    worker_view = operations_policy.evaluate_autopilot_policy(
        db_session,
        user,
        NOW,
        exclude_application_id=current.id,
    )
    assert worker_view.allowed is False
    assert worker_view.code == "application_cap_reached"
    assert worker_view.metadata["daily_count"] == 1
    assert worker_view.metadata["weekly_count"] == 1
