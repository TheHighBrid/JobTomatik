from datetime import datetime
from types import SimpleNamespace

from app.models.application import Application, ApplicationStatus
from app.models.intelligence import AgentRun
from app.models.job import Job, JobSource, JobStatus, JobType
from app.models.user import User
from app.services import operations_policy, unattended_policy
from app.services.application_queue_policy_runtime import (
    build_shared_evaluator,
    build_worker_evaluator,
    install_context_aware_cap_helpers,
)
from app.services.operations_policy import AutomationDecision


NOW = datetime(2026, 8, 24, 12, 0, 0)


def _user(db_session, *, complete_policy=True):
    settings = {
        "auto_apply_daily_limit": 1,
        "auto_apply_weekly_limit": 1,
    }
    if complete_policy:
        settings.update(
            {
                "autopilot_allowed_roles": ["fraud analyst"],
                "autopilot_allowed_workplace_modes": ["remote"],
                "autopilot_authorized_countries": ["CA"],
                "autopilot_allow_sponsorship_required": False,
                "autopilot_daily_platform_limits": {"greenhouse": 1},
            }
        )
    user = User(
        email=f"runtime-{int(complete_policy)}@example.com",
        hashed_password="not-used",
        automation_settings=settings,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _job(db_session):
    job = Job(
        external_id="gh-day30-runtime",
        title="Senior Fraud Analyst",
        company="Acme",
        location="Remote",
        salary_min=90000,
        seniority="senior",
        url="https://boards.greenhouse.io/acme/jobs/456",
        source=JobSource.greenhouse,
        status=JobStatus.queued,
        job_type=JobType.remote,
        raw_data={
            "remote_status": "remote",
            "requires_sponsorship": False,
            "country_code": "CA",
            "language": "english",
        },
    )
    db_session.add(job)
    db_session.flush()
    return job


def _operations_settings():
    return SimpleNamespace(
        global_kill_switch=False,
        autopilot_enabled=True,
        default_daily_cap=1,
        default_weekly_cap=1,
        quiet_hours_start_utc=0,
        quiet_hours_end_utc=0,
        failure_threshold=3,
        failure_window_minutes=60,
        circuit_breaker_minutes=120,
        stale_attempt_minutes=30,
        disabled_platforms="",
    )


def test_worker_recheck_excludes_only_its_current_application_from_caps(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    job = _job(db_session)
    app = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        application_target_url=job.url,
    )
    db_session.add(app)
    db_session.flush()

    monkeypatch.setattr(
        operations_policy,
        "get_operations_settings",
        _operations_settings,
    )
    install_context_aware_cap_helpers()

    def inherited_operations_gate(db, candidate_user, candidate_job, now=None):
        return unattended_policy.evaluate_autopilot_policy(
            db,
            candidate_user,
            now or NOW,
        )

    shared = build_shared_evaluator(inherited_operations_gate)
    worker = build_worker_evaluator(shared)

    # A scheduler-time evaluation sees the already-created row and therefore treats
    # the one-per-day cap as exhausted.
    scheduler_decision = shared(db_session, user, job, now=NOW)
    assert scheduler_decision.allowed is False
    assert scheduler_decision.code == "application_cap_reached"

    # The worker is rechecking that exact row, so it excludes only itself from the
    # inherited global count and from the Day 30 per-platform count.
    worker_decision = worker(db_session, user, job, now=NOW)
    assert worker_decision.allowed is True
    assert worker_decision.code == "day30_queue_policy_allowed"
    assert worker_decision.metadata["daily_count"] == 0
    assert worker_decision.metadata["platform_daily_count"] == 0
    assert worker_decision.metadata["platform_daily_cap"] == 1


def test_ambiguous_active_application_rows_do_not_under_count(db_session, monkeypatch):
    user = _user(db_session)
    job = _job(db_session)
    for _ in range(2):
        db_session.add(
            Application(
                user_id=user.id,
                job_id=job.id,
                status=ApplicationStatus.pending,
                application_target_url=job.url,
            )
        )
    db_session.flush()

    monkeypatch.setattr(
        operations_policy,
        "get_operations_settings",
        _operations_settings,
    )
    install_context_aware_cap_helpers()

    def inherited_operations_gate(db, candidate_user, candidate_job, now=None):
        return unattended_policy.evaluate_autopilot_policy(
            db,
            candidate_user,
            now or NOW,
        )

    decision = build_worker_evaluator(
        build_shared_evaluator(inherited_operations_gate)
    )(db_session, user, job, now=NOW)
    assert decision.allowed is False
    assert decision.code == "application_cap_reached"


def test_explicit_no_submit_shadow_profile_keeps_inherited_bypass(db_session):
    user = _user(db_session, complete_policy=False)
    job = _job(db_session)

    def inherited_shadow_gate(db, candidate_user, candidate_job, now=None):
        return AutomationDecision(
            True,
            "shadow_dry_run_maturity_exception",
            "Inherited no-submit shadow policy passed.",
            {
                "shadow_policy_candidate": True,
                "shadow_dry_run": True,
                "real_submission_enabled": False,
                "shadow_business_limits_bypassed": True,
                "shadow_suitability_filters_bypassed": True,
            },
        )

    before = db_session.query(AgentRun).count()
    decision = build_shared_evaluator(inherited_shadow_gate)(
        db_session,
        user,
        job,
        now=NOW,
    )
    after = db_session.query(AgentRun).count()

    assert decision.allowed is True
    assert decision.code == "shadow_dry_run_maturity_exception"
    assert decision.metadata["shadow_suitability_filters_bypassed"] is True
    assert before == after
