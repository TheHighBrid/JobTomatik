from datetime import datetime, timedelta

from app.models.application import Application, ManualReviewReason, ManualReviewTask
from app.models.job import Job
from app.models.user import User
from app.services.operations_policy import (
    disabled_platforms,
    evaluate_autopilot_policy,
    evaluate_platform_policy,
    is_quiet_hour,
    operations_readiness_manifest,
    platform_key_for_url,
)
from app.services.operations_settings import get_operations_settings
from app.tasks.scraping import daily_auto_search_all


def _reset_operations_settings():
    get_operations_settings.cache_clear()


def _user(db_session, email="ops@example.test"):
    user = User(
        email=email,
        hashed_password="test-hash",
        automation_settings={
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
        },
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _application(db_session, user, index, created_at):
    job = Job(
        external_id=f"ops-job-{index}",
        title=f"Operations Test {index}",
        company="Certification Company",
        url="https://boards.greenhouse.io/example/jobs/123",
    )
    db_session.add(job)
    db_session.flush()
    app = Application(
        user_id=user.id,
        job_id=job.id,
        submission_idempotency_key=f"ops:{user.id}:{index}",
        created_at=created_at,
    )
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)
    return app


def test_autopilot_and_real_submission_default_off(monkeypatch):
    for name in (
        "AUTOPILOT_ENABLED",
        "AUTOPILOT_DEFAULT_DAILY_CAP",
        "AUTOPILOT_DEFAULT_WEEKLY_CAP",
        "AUTOPILOT_DISABLED_PLATFORMS",
    ):
        monkeypatch.delenv(name, raising=False)
    _reset_operations_settings()

    manifest = operations_readiness_manifest()
    assert manifest["autopilot_enabled"] is False
    assert manifest["real_submission_enabled"] is False
    assert manifest["invariants"]["autopilot_defaults_off"] is True
    assert manifest["invariants"]["real_submission_defaults_off"] is True


def test_scheduled_task_is_inert_when_global_gate_is_off(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    _reset_operations_settings()

    result = daily_auto_search_all.run()
    assert result["skipped"] is True
    assert result["reason"] == "global_autopilot_disabled"
    assert result["applications_queued"] == 0


def test_quiet_hours_support_normal_wraparound_and_disabled_windows():
    noon = datetime(2026, 7, 16, 12, 0, 0)
    late = datetime(2026, 7, 16, 23, 0, 0)
    early = datetime(2026, 7, 16, 3, 0, 0)

    assert is_quiet_hour(noon, 9, 17) is True
    assert is_quiet_hour(late, 22, 6) is True
    assert is_quiet_hour(early, 22, 6) is True
    assert is_quiet_hour(noon, 22, 6) is False
    assert is_quiet_hour(noon, 0, 0) is False


def test_platform_detection_and_disable_list(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "workday, smartrecruiters")
    _reset_operations_settings()

    assert platform_key_for_url("https://acme.wd5.myworkdayjobs.com/en-US/jobs/job/R-1") == "workday"
    assert platform_key_for_url("https://jobs.lever.co/acme/abc") == "lever"
    assert platform_key_for_url("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert disabled_platforms() == {"workday", "smartrecruiters"}
    assert evaluate_platform_policy("https://acme.wd5.myworkdayjobs.com/job/R-1").allowed is False
    assert evaluate_platform_policy("https://jobs.lever.co/acme/abc").allowed is True


def test_daily_cap_blocks_new_scheduled_applications(db_session, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_DEFAULT_DAILY_CAP", "2")
    monkeypatch.setenv("AUTOPILOT_DEFAULT_WEEKLY_CAP", "10")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_START_UTC", "0")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_END_UTC", "0")
    _reset_operations_settings()

    # Keep the fixture inside one UTC calendar day. The production policy uses
    # UTC day boundaries, so wall-clock execution near midnight must not alter
    # what this regression test is exercising.
    now = datetime(2026, 7, 16, 12, 0, 0)
    user = _user(db_session, "cap@example.test")
    _application(db_session, user, 1, now - timedelta(hours=2))
    _application(db_session, user, 2, now - timedelta(hours=1))

    decision = evaluate_autopilot_policy(db_session, user, now)
    assert decision.allowed is False
    assert decision.code == "application_cap_reached"
    assert decision.metadata["daily_count"] == 2
    assert decision.metadata["remaining_daily"] == 0


def test_repeated_operational_failures_open_circuit_breaker(db_session, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_DEFAULT_DAILY_CAP", "20")
    monkeypatch.setenv("AUTOPILOT_DEFAULT_WEEKLY_CAP", "50")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_START_UTC", "0")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_END_UTC", "0")
    monkeypatch.setenv("AUTOPILOT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("AUTOPILOT_FAILURE_WINDOW_MINUTES", "60")
    monkeypatch.setenv("AUTOPILOT_CIRCUIT_BREAKER_MINUTES", "120")
    _reset_operations_settings()

    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session, "breaker@example.test")
    app = _application(db_session, user, 3, now - timedelta(hours=2))
    for offset in (30, 20, 10):
        db_session.add(ManualReviewTask(
            application_id=app.id,
            reason_code=ManualReviewReason.automation_error.value,
            summary="Synthetic operational failure",
            created_at=now - timedelta(minutes=offset),
        ))
    db_session.commit()

    decision = evaluate_autopilot_policy(db_session, user, now)
    assert decision.allowed is False
    assert decision.code == "circuit_breaker_open"
    assert decision.metadata["threshold"] == 3


def test_operations_readiness_endpoint(client, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    _reset_operations_settings()

    response = client.get("/api/system/operations-readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["autopilot_enabled"] is False
    assert payload["real_submission_enabled"] is False
