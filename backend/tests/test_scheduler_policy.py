from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.models.application import Application
from app.models.job import Job, JobStatus, JobSource
from app.models.user import User
from app.services.operations_settings import get_operations_settings
from app.services.scheduler_policy import (
    SCHEDULER_DEFAULTS,
    build_search_plan,
    candidate_priority,
    build_scheduler_preview,
)
from app.tasks.scraping import _run_scheduler_cycle_for_user


def _reset_operations_settings():
    get_operations_settings.cache_clear()


def _user(db_session, *, email="scheduler@example.test", automation=None, preferences=None):
    user = User(
        email=email,
        hashed_password="test-hash",
        automation_settings=automation or {},
        job_preferences=preferences or {},
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_scheduler_defaults_are_fail_safe(auth_client):
    response = auth_client.get("/api/settings")
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run_mode"] is True
    assert payload["auto_search_enabled"] is False
    assert payload["auto_apply_enabled"] is False
    assert SCHEDULER_DEFAULTS["autopilot_enabled_platforms"] == []


def test_scheduler_settings_reject_unknown_source(auth_client):
    response = auth_client.patch(
        "/api/settings",
        json={"scheduler_search_sources": ["jobbank", "mystery-board"]},
    )
    assert response.status_code == 422


def test_partial_settings_patch_validates_against_saved_caps(auth_client):
    first = auth_client.patch(
        "/api/settings",
        json={
            "auto_apply_daily_limit": 5,
            "auto_apply_weekly_limit": 10,
        },
    )
    assert first.status_code == 200

    second = auth_client.patch(
        "/api/settings",
        json={"auto_apply_daily_limit": 15},
    )
    assert second.status_code == 422


def test_partial_settings_patch_rejects_saved_allow_exclude_overlap(auth_client):
    first = auth_client.patch(
        "/api/settings",
        json={"autopilot_employer_allow_list": ["Acme"]},
    )
    assert first.status_code == 200

    second = auth_client.patch(
        "/api/settings",
        json={"autopilot_employer_exclude_list": ["acme"]},
    )
    assert second.status_code == 422


def test_search_plan_fails_closed_without_keywords_or_location(db_session):
    user = _user(
        db_session,
        automation={
            "auto_search_enabled": True,
            "scheduler_search_sources": ["jobbank"],
        },
    )
    plan = build_search_plan(user)
    assert plan["ready"] is False
    assert plan["reason_code"] == "search_keywords_missing"
    assert plan["search_params"] is None
    assert "AML analyst" not in plan["reason"]
    assert "Ottawa" not in plan["reason"]


def test_search_plan_uses_saved_or_profile_owned_values(db_session):
    user = _user(
        db_session,
        automation={
            "auto_search_enabled": True,
            "scheduler_search_sources": ["jobbank", "lever"],
        },
        preferences={
            "preferred_titles": ["Fraud investigator", "Risk analyst"],
            "preferred_locations": ["Montreal, Quebec"],
            "min_salary": 70000,
        },
    )
    plan = build_search_plan(user)
    assert plan["ready"] is True
    params = plan["search_params"]
    assert params["keywords"] == "Fraud investigator, Risk analyst"
    assert params["location"] == "Montreal, Quebec"
    assert params["salary_min"] == 70000
    assert params["sources"] == ["jobbank", "lever"]


def test_deadline_priority_boosts_urgent_open_posting():
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    urgent = Job(
        title="Urgent role",
        company="Acme",
        relevance_score=0.8,
        raw_data={"application_deadline": (now + timedelta(hours=20)).isoformat()},
    )
    later = Job(
        title="Later role",
        company="Acme",
        relevance_score=0.8,
        raw_data={"application_deadline": (now + timedelta(days=20)).isoformat()},
    )
    urgent_score, urgent_evidence = candidate_priority(urgent, now)
    later_score, _ = candidate_priority(later, now)
    assert urgent_score > later_score
    assert urgent_evidence["urgency_boost"] == 18.0


def test_preview_stays_globally_disabled_when_autopilot_env_is_off(db_session, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    _reset_operations_settings()
    user = _user(
        db_session,
        automation={"auto_search_enabled": True},
        preferences={
            "preferred_titles": ["Risk analyst"],
            "preferred_locations": ["Ottawa, Ontario"],
        },
    )
    preview = build_scheduler_preview(db_session, user)
    assert preview["scheduler_state"] == "globally_disabled"
    assert preview["global_autopilot_enabled"] is False
    assert preview["invariants"]["certified_autonomous_required"] is True
    assert preview["invariants"]["dry_run_defaults_on"] is True


def test_scheduler_run_endpoint_cannot_bypass_global_autopilot(auth_client, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    _reset_operations_settings()
    saved = auth_client.patch(
        "/api/settings",
        json={
            "auto_search_enabled": True,
            "scheduler_search_keywords": ["Risk analyst"],
            "scheduler_search_location": "Ottawa, Ontario",
            "scheduler_search_sources": ["jobbank"],
        },
    )
    assert saved.status_code == 200
    response = auth_client.post("/api/scheduler/run")
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTOPILOT_ENABLED is false"


def test_user_scheduler_cycle_never_invents_missing_search_identity(db_session, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_START_UTC", "0")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_END_UTC", "0")
    _reset_operations_settings()

    user = _user(
        db_session,
        email="no-search-identity@example.test",
        automation={
            "auto_search_enabled": True,
            "auto_apply_enabled": False,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
            "scheduler_search_sources": ["jobbank"],
        },
    )
    fake_delay = MagicMock()
    monkeypatch.setattr("app.tasks.scraping.run_job_search.delay", fake_delay)

    result = _run_scheduler_cycle_for_user(db_session, user)
    assert result["searched"] is False
    assert result["search_blocker"]["code"] == "search_keywords_missing"
    fake_delay.assert_not_called()


def test_application_cap_blocks_apply_but_not_discovery(db_session, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_DEFAULT_DAILY_CAP", "1")
    monkeypatch.setenv("AUTOPILOT_DEFAULT_WEEKLY_CAP", "10")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_START_UTC", "0")
    monkeypatch.setenv("AUTOPILOT_QUIET_HOURS_END_UTC", "0")
    _reset_operations_settings()

    user = _user(
        db_session,
        email="cap-discovery@example.test",
        automation={
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "auto_apply_daily_limit": 1,
            "auto_apply_weekly_limit": 10,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
            "scheduler_search_keywords": ["Risk analyst"],
            "scheduler_search_location": "Ottawa, Ontario",
            "scheduler_search_sources": ["jobbank"],
        },
    )
    previous_job = Job(
        external_id="cap-existing",
        title="Existing application",
        company="Previous Co",
        status=JobStatus.applied,
        source=JobSource.manual,
        url="https://example.com/jobs/1",
    )
    db_session.add(previous_job)
    db_session.flush()
    db_session.add(Application(user_id=user.id, job_id=previous_job.id))
    db_session.commit()

    fake_delay = MagicMock()
    monkeypatch.setattr("app.tasks.scraping.run_job_search.delay", fake_delay)

    result = _run_scheduler_cycle_for_user(db_session, user)
    assert result["searched"] is True
    assert result["applications_queued"] == 0
    assert result["reason"] == "application_cap_reached"
    fake_delay.assert_called_once()


def test_scheduler_preview_ranks_policy_candidates_without_mutating_jobs(db_session, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    _reset_operations_settings()
    user = _user(
        db_session,
        email="preview@example.test",
        automation={"auto_apply_enabled": True, "auto_apply_min_score": 0.5},
    )
    job = Job(
        external_id="sched-preview-1",
        title="Risk analyst",
        company="Preview Co",
        location="ottawa, ontario",
        salary_min=90000,
        source=JobSource.manual,
        status=JobStatus.queued,
        relevance_score=0.91,
        seniority="mid",
        url="https://jobs.lever.co/preview/abc",
        raw_data={
            "language": "english",
            "requires_sponsorship": False,
        },
    )
    db_session.add(job)
    db_session.commit()

    preview = build_scheduler_preview(db_session, user)
    assert preview["summary"]["candidate_count"] == 1
    assert preview["candidates"][0]["job_id"] == job.id
    assert preview["candidates"][0]["policy_decision"]["allowed"] is False
    assert preview["invariants"]["application_caps_do_not_stop_discovery"] is True
    db_session.refresh(job)
    assert job.status == JobStatus.queued
