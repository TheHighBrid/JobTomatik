from __future__ import annotations

from types import SimpleNamespace

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import operations_policy, scheduler_policy, unattended_policy
from app.services.operations_policy import SHADOW_TEST_POLICY_PROFILE
from app.services.operations_settings import OperationsSettings
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION
from app.tasks import applications, scraping, unattended


def _operations() -> OperationsSettings:
    return OperationsSettings(
        global_kill_switch=False,
        autopilot_enabled=True,
        default_daily_cap=5,
        default_weekly_cap=20,
        quiet_hours_start_utc=0,
        quiet_hours_end_utc=0,
        failure_threshold=3,
        failure_window_minutes=60,
        circuit_breaker_minutes=120,
        stale_attempt_minutes=30,
        disabled_platforms="",
    )


def _user(db_session, *, email: str, employer_limit: int = 1) -> User:
    user = User(
        email=email,
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "auto_search_enabled": False,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
            "auto_apply_min_score": 0.0,
            "auto_apply_daily_limit": 5,
            "auto_apply_weekly_limit": 20,
            "auto_apply_daily_per_employer_limit": employer_limit,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
            "autopilot_enabled_platforms": ["lever"],
        },
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _lever_job(
    *,
    external_id: str,
    company: str = "EQ Bank",
    status: JobStatus = JobStatus.queued,
) -> Job:
    return Job(
        external_id=external_id,
        title="Risk Analyst",
        company=company,
        location="ottawa, ontario",
        salary_min=90000,
        seniority="mid",
        source=JobSource.lever,
        status=status,
        relevance_score=0.99,
        url=f"https://jobs.lever.co/eqbank/{external_id}",
        raw_data={
            "language": "english",
            "requires_sponsorship": False,
            "application_method": "lever",
        },
    )


def _patch_policy_dependencies(monkeypatch) -> None:
    operations = _operations()
    for module in (operations_policy, scheduler_policy, unattended_policy):
        monkeypatch.setattr(module, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(
        unattended_policy,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=False),
    )
    monkeypatch.setattr(
        unattended_policy,
        "live_platform_maturities",
        lambda: {
            "greenhouse": "dry_run",
            "lever": "certified_autonomous",
            "ashby": "dry_run",
            "smartrecruiters": "dry_run",
            "workday": "dry_run",
            "generic": None,
        },
    )
    monkeypatch.setattr(
        scraping,
        "settings",
        SimpleNamespace(allow_real_application_submit=False),
    )


def test_shadow_test_profile_bypasses_global_daily_and_weekly_caps(
    db_session,
    monkeypatch,
):
    _patch_policy_dependencies(monkeypatch)
    user = _user(db_session, email="shadow-global-caps@example.test")

    for index in range(5):
        job = _lever_job(external_id=f"prior-cap-{index}", company=f"Prior {index}")
        db_session.add(job)
        db_session.flush()
        db_session.add(
            Application(
                user_id=user.id,
                job_id=job.id,
                submission_idempotency_key=f"prior-cap-{index}",
            )
        )
    db_session.commit()

    production = operations_policy.evaluate_autopilot_policy(db_session, user)
    assert production.allowed is False
    assert production.code == "application_cap_reached"

    shadow = operations_policy.evaluate_autopilot_policy(
        db_session,
        user,
        policy_profile=SHADOW_TEST_POLICY_PROFILE,
    )
    assert shadow.allowed is True
    assert shadow.code == "shadow_test_policy_allowed"
    assert shadow.metadata["production_caps_enforced"] is False
    assert shadow.metadata["quiet_hours_enforced"] is False
    assert shadow.metadata["circuit_breaker_enforced"] is False
    assert shadow.metadata["daily_count"] == 5


def test_shadow_test_profile_ignores_prior_same_employer_applications(
    db_session,
    monkeypatch,
):
    _patch_policy_dependencies(monkeypatch)
    user = _user(
        db_session,
        email="shadow-employer-cap@example.test",
        employer_limit=1,
    )

    for index in range(4):
        prior_job = _lever_job(external_id=f"eq-prior-{index}")
        db_session.add(prior_job)
        db_session.flush()
        db_session.add(
            Application(
                user_id=user.id,
                job_id=prior_job.id,
                submission_idempotency_key=f"eq-prior-app-{index}",
            )
        )
    candidate = _lever_job(external_id="eq-fresh-candidate")
    db_session.add(candidate)
    db_session.commit()

    production = unattended_policy.evaluate_unattended_job_policy(
        db_session,
        user,
        candidate,
    )
    assert production.allowed is False
    assert production.code == "employer_daily_cap_reached"

    with unattended_policy.shadow_dry_run_policy_context(
        shadow_session_id=9001,
        dry_run=True,
    ):
        shadow = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            user,
            candidate,
        )

    assert shadow.allowed is True
    assert shadow.metadata["shadow_business_limits_bypassed"] is True
    assert shadow.metadata["policy_profile"] == SHADOW_TEST_POLICY_PROFILE


def test_shadow_retry_can_reuse_prior_shadow_approved_posting_without_collision(
    db_session,
    monkeypatch,
):
    _patch_policy_dependencies(monkeypatch)
    user = _user(
        db_session,
        email="shadow-retry@example.test",
        employer_limit=1,
    )
    job = _lever_job(
        external_id="same-posting",
        status=JobStatus.approved,
    )
    db_session.add(job)
    db_session.flush()

    prior = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key=f"application:{user.id}:job:{job.id}:shadow:111",
    )
    db_session.add(prior)
    db_session.flush()
    db_session.add(
        ApplicationEvent(
            application_id=prior.id,
            event_type="application_created",
            from_state=None,
            to_state=ApplicationAutomationState.preparing.value,
            payload={
                "job_id": job.id,
                "source": "full_stack_shadow_scheduler",
                "dry_run": True,
                "shadow_session_id": 111,
            },
        )
    )
    db_session.commit()

    projection = SimpleNamespace(
        id=int(user.id),
        automation_settings=dict(user.automation_settings or {}),
        job_preferences=dict(user.job_preferences or {}),
        _qualification_candidate_job_ids=(int(job.id),),
    )

    monkeypatch.setattr(
        applications.generate_cover_letter_task,
        "delay",
        lambda application_id: SimpleNamespace(id=f"cover-{application_id}"),
    )
    dispatches: list[dict] = []

    def capture_dispatch(*, args, kwargs, countdown):
        dispatches.append(
            {
                "args": list(args),
                "kwargs": dict(kwargs),
                "countdown": countdown,
            }
        )
        return SimpleNamespace(id=f"worker-{args[0]}")

    monkeypatch.setattr(
        unattended.submit_unattended_application_task,
        "apply_async",
        capture_dispatch,
    )

    result = scraping._run_scheduler_cycle_for_user(
        db_session,
        projection,
        shadow_session_id=222,
        shadow_application_limit=1,
    )

    assert result["applications_queued"] == 1
    assert result["application_ids_queued"]
    assert result["policy_profile"] == SHADOW_TEST_POLICY_PROFILE
    assert result["production_limits_enforced"] is False
    assert result["blocked_job_reasons"].get("employer_daily_cap_reached", 0) == 0
    assert result["blocked_job_reasons"].get("existing_application", 0) == 0
    assert len(dispatches) == 1
    assert dispatches[0]["kwargs"] == {
        "dry_run": True,
        "shadow_session_id": 222,
    }

    current = (
        db_session.query(Application)
        .filter(Application.id == result["application_ids_queued"][0])
        .one()
    )
    assert current.submission_idempotency_key == (
        f"application:{user.id}:job:{job.id}:shadow:222"
    )
    assert int(current.id) != int(prior.id)
