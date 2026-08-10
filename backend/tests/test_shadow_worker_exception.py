from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.certification import ShadowRunSession
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import unattended_policy
from app.services.operations_policy import AutomationDecision
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION
from app.tasks import scraping, unattended


NOW = datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)


def _policy_user_and_job(db_session):
    user = User(
        email="shadow-exception-policy@example.test",
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "autopilot_enabled_platforms": ["lever"],
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
            "auto_apply_daily_per_employer_limit": 5,
        },
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    job = Job(
        external_id="shadow-exception-policy-job",
        title="Risk analyst",
        company="Policy Example Co",
        location="ottawa, ontario",
        salary_min=90000,
        seniority="mid",
        source=JobSource.lever,
        status=JobStatus.queued,
        relevance_score=0.95,
        url="https://jobs.lever.co/policy-example/role-1",
        raw_data={"language": "english", "requires_sponsorship": False},
    )
    db_session.add(job)
    db_session.commit()
    return user, job


def _install_other_policy_gates_as_safe(monkeypatch):
    monkeypatch.setattr(
        unattended_policy,
        "evaluate_autopilot_policy",
        lambda db, user, now=None: AutomationDecision(
            True,
            "autopilot_allowed",
            "allowed",
            {
                "daily_count": 0,
                "weekly_count": 0,
                "daily_cap": 10,
                "weekly_cap": 20,
            },
        ),
    )
    monkeypatch.setattr(
        unattended_policy,
        "get_operations_settings",
        lambda: SimpleNamespace(
            autopilot_enabled=True,
            quiet_hours_start_utc=0,
            quiet_hours_end_utc=0,
            failure_threshold=5,
        ),
    )
    monkeypatch.setattr(unattended_policy, "disabled_platforms", lambda: set())
    monkeypatch.setattr(
        unattended_policy,
        "live_platform_maturities",
        lambda: {"lever": "dry_run"},
    )


def test_maturity_exception_exists_only_in_safe_shadow_context(db_session, monkeypatch):
    user, job = _policy_user_and_job(db_session)
    _install_other_policy_gates_as_safe(monkeypatch)
    core = SimpleNamespace(allow_real_application_submit=False)
    monkeypatch.setattr(unattended_policy, "get_settings", lambda: core)

    ordinary = unattended_policy.evaluate_unattended_job_policy(
        db_session,
        user,
        job,
        now=NOW.replace(tzinfo=None),
    )
    assert ordinary.allowed is False
    assert ordinary.code == "platform_not_certified"
    assert ordinary.metadata["shadow_dry_run_maturity_exception"] is False

    with unattended_policy.shadow_dry_run_policy_context(
        shadow_session_id=77,
        dry_run=True,
    ):
        shadow = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            user,
            job,
            now=NOW.replace(tzinfo=None),
        )
    assert shadow.allowed is True
    assert shadow.code == "shadow_dry_run_maturity_exception"
    assert shadow.metadata["platform_maturity"] == "dry_run"
    assert shadow.metadata["shadow_session_id"] == 77
    assert shadow.metadata["shadow_dry_run"] is True
    assert shadow.metadata["real_submission_enabled"] is False
    assert shadow.metadata["shadow_dry_run_maturity_exception"] is True

    with unattended_policy.shadow_dry_run_policy_context(
        shadow_session_id=77,
        dry_run=False,
    ):
        not_dry = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            user,
            job,
            now=NOW.replace(tzinfo=None),
        )
    assert not_dry.allowed is False
    assert not_dry.code == "platform_not_certified"
    assert not_dry.metadata["shadow_dry_run_maturity_exception"] is False

    core.allow_real_application_submit = True
    with unattended_policy.shadow_dry_run_policy_context(
        shadow_session_id=77,
        dry_run=True,
    ):
        live_enabled = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            user,
            job,
            now=NOW.replace(tzinfo=None),
        )
    assert live_enabled.allowed is False
    assert live_enabled.code == "platform_not_certified"
    assert live_enabled.metadata["real_submission_enabled"] is True
    assert live_enabled.metadata["shadow_dry_run_maturity_exception"] is False


@pytest.mark.parametrize(
    ("user_dry_run", "real_submission_enabled"),
    [(False, False), (True, True), (False, True)],
)
def test_shadow_scheduler_blocks_before_any_application_worker_dispatch(
    monkeypatch,
    user_dry_run,
    real_submission_enabled,
):
    user = SimpleNamespace(id=912)
    monkeypatch.setattr(
        scraping,
        "scheduler_settings",
        lambda _user: {
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": user_dry_run,
        },
    )
    monkeypatch.setattr(
        scraping,
        "settings",
        SimpleNamespace(allow_real_application_submit=real_submission_enabled),
    )
    rank = MagicMock()
    dispatch = MagicMock()
    monkeypatch.setattr(scraping, "rank_scheduler_candidates", rank)
    monkeypatch.setattr(
        "app.tasks.unattended.submit_unattended_application_task.apply_async",
        dispatch,
    )

    result = scraping._run_scheduler_cycle_for_user(
        MagicMock(),
        user,
        shadow_session_id=441,
    )

    assert result["reason"] == "shadow_safety_invariant_blocked"
    assert result["applications_queued"] == 0
    assert result["searched"] is False
    assert result["shadow_session_id"] == 441
    rank.assert_not_called()
    dispatch.assert_not_called()


def _shadow_application(db_session, *, email: str):
    user = User(
        email=email,
        hashed_password="test-hash",
        automation_settings={"scheduler_policy_version": SCHEDULER_POLICY_VERSION},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    job = Job(
        external_id=f"{email}-job",
        title="Shadow QA",
        company="Shadow Worker Co",
        location="remote",
        salary_min=90000,
        seniority="mid",
        source=JobSource.lever,
        status=JobStatus.approved,
        relevance_score=0.99,
        url="https://jobs.lever.co/shadow-worker/role-1",
        raw_data={"language": "english", "requires_sponsorship": False},
    )
    db_session.add(job)
    db_session.flush()
    session = ShadowRunSession(
        user_id=user.id,
        candidate_revision="a" * 40,
        target_evidence_type="shadow_run_4h",
        requested_duration_seconds=4 * 60 * 60,
        cycle_interval_seconds=60,
        status="running",
        started_at=NOW,
        expected_end_at=NOW + timedelta(hours=4),
        settle_deadline_at=NOW + timedelta(hours=4, minutes=45),
        last_heartbeat_at=NOW,
        final_submit_allowed=False,
        configuration_snapshot={
            "invariants": {
                "dry_run_required": True,
                "real_submission_must_remain_disabled": True,
                "final_submit_allowed": False,
            }
        },
        baseline_snapshot={},
    )
    db_session.add(session)
    db_session.flush()
    app = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.preparing.value,
        submission_idempotency_key=f"shadow-worker:{session.id}:{job.id}",
    )
    db_session.add(app)
    db_session.flush()
    db_session.add(
        ApplicationEvent(
            application_id=app.id,
            event_type="application_created",
            from_state=None,
            to_state=ApplicationAutomationState.preparing.value,
            payload={
                "job_id": job.id,
                "source": "full_stack_shadow_scheduler",
                "dry_run": True,
                "shadow_session_id": session.id,
            },
            created_at=NOW,
        )
    )
    db_session.commit()
    return user, job, session, app


def _allow_worker_policy(monkeypatch):
    monkeypatch.setattr(
        unattended,
        "evaluate_unattended_job_policy",
        lambda db, user, job: SimpleNamespace(allowed=True),
    )


def test_worker_derives_shadow_context_and_rejects_non_dry_run_before_submit(
    db_session,
    monkeypatch,
):
    _, _, _, app = _shadow_application(
        db_session,
        email="shadow-worker-dry-run@example.test",
    )
    monkeypatch.setattr(unattended, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        unattended,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=False),
    )
    _allow_worker_policy(monkeypatch)
    downstream = MagicMock(return_value={"success": True})
    monkeypatch.setattr("app.tasks.applications.submit_application_task.run", downstream)

    # Deliberately omit shadow_session_id. The worker must derive it from the
    # persisted application event instead of falling back to an ordinary live path.
    result = unattended.submit_unattended_application_task.run(
        app.id,
        dry_run=False,
    )

    assert result["success"] is False
    assert result["error"] == "shadow_worker_requires_dry_run"
    downstream.assert_not_called()


def test_worker_rechecks_global_no_submit_after_shadow_task_was_queued(
    db_session,
    monkeypatch,
):
    _, _, session, app = _shadow_application(
        db_session,
        email="shadow-worker-real-submit@example.test",
    )
    monkeypatch.setattr(unattended, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        unattended,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=True),
    )
    _allow_worker_policy(monkeypatch)
    downstream = MagicMock(return_value={"success": True})
    monkeypatch.setattr("app.tasks.applications.submit_application_task.run", downstream)

    result = unattended.submit_unattended_application_task.run(
        app.id,
        dry_run=True,
        shadow_session_id=session.id,
    )

    assert result["success"] is False
    assert result["error"] == "shadow_worker_requires_real_submission_disabled"
    downstream.assert_not_called()


def test_fake_shadow_id_cannot_grant_exception_to_normal_application(
    db_session,
    monkeypatch,
):
    user = User(
        email="fake-shadow-context@example.test",
        hashed_password="test-hash",
        automation_settings={"scheduler_policy_version": SCHEDULER_POLICY_VERSION},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    job = Job(
        external_id="fake-shadow-job",
        title="Normal job",
        company="Normal Co",
        location="remote",
        source=JobSource.lever,
        status=JobStatus.approved,
        url="https://jobs.lever.co/normal/role-1",
    )
    db_session.add(job)
    db_session.flush()
    app = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.preparing.value,
    )
    db_session.add(app)
    db_session.flush()
    db_session.add(
        ApplicationEvent(
            application_id=app.id,
            event_type="application_created",
            from_state=None,
            to_state=ApplicationAutomationState.preparing.value,
            payload={"source": "bounded_scheduler", "dry_run": True},
            created_at=NOW,
        )
    )
    db_session.commit()

    monkeypatch.setattr(unattended, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        unattended,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=False),
    )
    _allow_worker_policy(monkeypatch)
    downstream = MagicMock(return_value={"success": True})
    monkeypatch.setattr("app.tasks.applications.submit_application_task.run", downstream)

    result = unattended.submit_unattended_application_task.run(
        app.id,
        dry_run=True,
        shadow_session_id=999999,
    )

    assert result["success"] is False
    assert result["error"] == "shadow_worker_application_not_correlated"
    downstream.assert_not_called()


def test_valid_shadow_context_can_reach_submit_worker_only_as_dry_run(
    db_session,
    monkeypatch,
):
    _, _, session, app = _shadow_application(
        db_session,
        email="shadow-worker-valid@example.test",
    )
    monkeypatch.setattr(unattended, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        unattended,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=False),
    )
    _allow_worker_policy(monkeypatch)
    downstream = MagicMock(return_value={"success": True, "dry_run": True})
    monkeypatch.setattr("app.tasks.applications.submit_application_task.run", downstream)

    result = unattended.submit_unattended_application_task.run(
        app.id,
        dry_run=True,
        shadow_session_id=session.id,
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    downstream.assert_called_once_with(app.id, dry_run=True)
