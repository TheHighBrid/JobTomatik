from datetime import datetime

import pytest
from pydantic import ValidationError

from app.api.settings import SettingsUpdate
from app.models.application import Application
from app.models.intelligence import AgentRun
from app.models.job import Job, JobSource, JobStatus, JobType
from app.models.user import User
from app.services.application_queue_policy import (
    build_policy_evaluator,
    classify_disposition,
    workplace_mode,
    work_authorization_country,
)
from app.services.operations_policy import AutomationDecision


NOW = datetime(2026, 8, 24, 12, 0, 0)


def _user(db_session, **settings):
    policy = {
        "autopilot_allowed_roles": ["fraud analyst"],
        "autopilot_allowed_workplace_modes": ["remote", "hybrid"],
        "autopilot_authorized_countries": ["CA"],
        "autopilot_allow_sponsorship_required": False,
        "autopilot_daily_platform_limits": {"greenhouse": 2},
    }
    policy.update(settings)
    user = User(
        email="day30@example.com",
        hashed_password="not-used",
        automation_settings=policy,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _job(db_session, **overrides):
    values = {
        "external_id": "gh-day30-1",
        "title": "Senior Fraud Analyst",
        "company": "Acme",
        "location": "Remote",
        "salary_min": 90000,
        "seniority": "senior",
        "url": "https://boards.greenhouse.io/acme/jobs/123",
        "source": JobSource.greenhouse,
        "status": JobStatus.queued,
        "job_type": JobType.remote,
        "raw_data": {
            "remote_status": "remote",
            "requires_sponsorship": False,
            "country_code": "CA",
            "language": "english",
        },
    }
    values.update(overrides)
    job = Job(**values)
    db_session.add(job)
    db_session.flush()
    return job


def _base_allow(db, user, job, now=None):
    return AutomationDecision(
        True,
        "inherited_allowed",
        "Inherited policy passed.",
        {"platform": "greenhouse"},
    )


def test_settings_reject_auto_apply_without_day30_policy():
    with pytest.raises(ValidationError) as exc:
        SettingsUpdate(
            auto_apply_enabled=True,
            autopilot_enabled_platforms=["greenhouse"],
        )
    text = str(exc.value)
    assert "autopilot_allowed_roles" in text
    assert "autopilot_allowed_workplace_modes" in text
    assert "autopilot_authorized_countries" in text
    assert "autopilot_daily_platform_limits.greenhouse" in text


def test_settings_accept_complete_day30_policy():
    settings = SettingsUpdate(
        auto_apply_enabled=True,
        autopilot_enabled_platforms=["greenhouse"],
        autopilot_allowed_roles=["Fraud Analyst"],
        autopilot_allowed_workplace_modes=["REMOTE"],
        autopilot_authorized_countries=["CA"],
        autopilot_daily_platform_limits={"GreenHouse": 2},
    )
    assert settings.autopilot_allowed_workplace_modes == ["remote"]
    assert settings.autopilot_daily_platform_limits == {"greenhouse": 2}


def test_workplace_and_country_extractors_are_conservative(db_session):
    job = _job(db_session)
    assert workplace_mode(job) == "remote"
    assert work_authorization_country(job) == "canada"

    unknown = _job(
        db_session,
        external_id="gh-day30-unknown",
        job_type=JobType.full_time,
        location="Ottawa",
        raw_data={"requires_sponsorship": False, "language": "english"},
    )
    assert workplace_mode(unknown) is None
    assert work_authorization_country(unknown) is None


def test_complete_policy_accepts_and_writes_durable_audit(db_session):
    user = _user(db_session)
    job = _job(db_session)
    evaluate = build_policy_evaluator(_base_allow)

    decision = evaluate(db_session, user, job, now=NOW)

    assert decision.allowed is True
    assert decision.code == "day30_queue_policy_allowed"
    assert decision.metadata["workplace_mode"] == "remote"
    assert decision.metadata["work_authorization_country"] == "canada"
    assert decision.metadata["platform_daily_cap"] == 2
    audit_id = decision.metadata["policy_audit_run_id"]
    audit = db_session.query(AgentRun).filter(AgentRun.id == audit_id).one()
    assert audit.result["disposition"] == "accepted"
    assert audit.result["code"] == "day30_queue_policy_allowed"
    assert audit.run_context["job_id"] == job.id


def test_role_workplace_authorization_and_sponsorship_are_fail_closed(db_session):
    evaluate = build_policy_evaluator(_base_allow)

    user = _user(db_session, autopilot_allowed_roles=["aml analyst"])
    role_job = _job(db_session)
    decision = evaluate(db_session, user, role_job, now=NOW)
    assert decision.allowed is False
    assert decision.code == "role_not_allowed"
    assert classify_disposition(decision) == "rejected"

    user.automation_settings = {
        **dict(user.automation_settings),
        "autopilot_allowed_roles": ["fraud analyst"],
        "autopilot_allowed_workplace_modes": ["hybrid"],
    }
    workplace_job = _job(db_session, external_id="gh-day30-2")
    decision = evaluate(db_session, user, workplace_job, now=NOW)
    assert decision.allowed is False
    assert decision.code == "workplace_mode_not_allowed"

    user.automation_settings = {
        **dict(user.automation_settings),
        "autopilot_allowed_workplace_modes": ["remote"],
        "autopilot_authorized_countries": ["US"],
    }
    auth_job = _job(db_session, external_id="gh-day30-3")
    decision = evaluate(db_session, user, auth_job, now=NOW)
    assert decision.allowed is False
    assert decision.code == "work_authorization_not_allowed"

    user.automation_settings = {
        **dict(user.automation_settings),
        "autopilot_authorized_countries": ["CA"],
        "autopilot_allow_sponsorship_required": False,
    }
    sponsor_job = _job(
        db_session,
        external_id="gh-day30-4",
        raw_data={
            "remote_status": "remote",
            "requires_sponsorship": True,
            "country_code": "CA",
            "language": "english",
        },
    )
    decision = evaluate(db_session, user, sponsor_job, now=NOW)
    assert decision.allowed is False
    assert decision.code == "sponsorship_required_not_allowed"


def test_unknown_job_policy_facts_are_held_not_guessed(db_session):
    user = _user(db_session)
    job = _job(
        db_session,
        job_type=JobType.full_time,
        location="Ottawa",
        raw_data={
            "requires_sponsorship": False,
            "language": "english",
        },
    )
    decision = build_policy_evaluator(_base_allow)(db_session, user, job, now=NOW)
    assert decision.allowed is False
    assert decision.code == "workplace_mode_unknown"
    assert classify_disposition(decision) == "held"


def test_per_platform_daily_cap_blocks_at_boundary(db_session):
    user = _user(db_session, autopilot_daily_platform_limits={"greenhouse": 1})
    previous_job = _job(db_session, external_id="gh-day30-prev")
    db_session.add(
        Application(
            user_id=user.id,
            job_id=previous_job.id,
            application_target_url=previous_job.url,
        )
    )
    db_session.flush()

    candidate = _job(db_session, external_id="gh-day30-next")
    decision = build_policy_evaluator(_base_allow)(
        db_session,
        user,
        candidate,
        now=datetime.utcnow(),
    )
    assert decision.allowed is False
    assert decision.code == "platform_daily_cap_reached"
    assert decision.metadata["platform_daily_count"] == 1
    assert decision.metadata["platform_daily_cap"] == 1
    assert classify_disposition(decision) == "held"


def test_inherited_block_is_never_weakened_and_is_audited(db_session):
    user = _user(db_session)
    job = _job(db_session)

    def inherited_block(db, user, job, now=None):
        return AutomationDecision(
            False,
            "quiet_hours",
            "Production quiet hours are active.",
            {"start_hour_utc": 0, "end_hour_utc": 6},
        )

    decision = build_policy_evaluator(inherited_block)(db_session, user, job, now=NOW)
    assert decision.allowed is False
    assert decision.code == "quiet_hours"
    assert classify_disposition(decision) == "held"
    audit = db_session.query(AgentRun).filter(
        AgentRun.id == decision.metadata["policy_audit_run_id"]
    ).one()
    assert audit.result["code"] == "quiet_hours"
    assert audit.result["disposition"] == "held"
