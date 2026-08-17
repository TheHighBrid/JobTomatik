from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.certification import ShadowRunSession
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import operations_policy, unattended_policy
from app.services.operations_settings import OperationsSettings
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION
from app.services.unattended_policy import shadow_dry_run_policy_context
from scripts import run_shadow_qualification_canary as canary


ATS_TARGET = {
    "provider": "lever",
    "identifier": "eqbank",
    "company": "EQ Bank",
}


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


def _session(db_session, user_id: int, target: str, *, qualification: bool) -> ShadowRunSession:
    now = datetime.now(timezone.utc)
    session = ShadowRunSession(
        user_id=user_id,
        candidate_revision="a" * 40,
        target_evidence_type=target,
        requested_duration_seconds=12 * 60 if qualification else 4 * 60 * 60,
        cycle_interval_seconds=60 if qualification else 15 * 60,
        status="running",
        started_at=now,
        expected_end_at=now + timedelta(minutes=12 if qualification else 240),
        settle_deadline_at=now + timedelta(minutes=17 if qualification else 285),
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot={
            "qualification_canary": qualification,
            "certification_eligible": False,
            "invariants": {
                "dry_run_required": True,
                "real_submission_must_remain_disabled": True,
                "final_submit_allowed": False,
                "submission_authorized": False,
                "outreach_authorized": False,
                "adapter_maturity_mutated": False,
            },
        },
        baseline_snapshot={},
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


def test_qualification_discovery_uses_only_eligible_public_ats_targets():
    search_plan = {
        "ready": True,
        "search_params": {
            "keywords": "Fraud, Risk, KYC, Compliance, AML",
            "location": "Ottawa, Ontario",
            "salary_min": 80000,
            "sources": ["jobbank", "linkedin", "indeed", "lever"],
            "ats_targets": [dict(ATS_TARGET)],
            "limit": 50,
        },
    }
    pre_policy = {
        "eligible_shadow_ats_targets": [
            {**ATS_TARGET, "maturity": "dry_run"},
        ]
    }

    params = canary._qualification_discovery_search_params(search_plan, pre_policy)

    assert params == {
        "keywords": "",
        "location": "",
        "salary_min": None,
        "salary_max": None,
        "job_type": None,
        "sources": ["lever"],
        "ats_targets": [ATS_TARGET],
        "limit": 50,
    }


def test_no_submit_shadow_testing_relaxes_suitability_for_canary_and_timed_campaign(
    db_session,
    monkeypatch,
):
    operations = _operations()
    monkeypatch.setattr(operations_policy, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(unattended_policy, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(
        unattended_policy,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=False),
    )
    monkeypatch.setattr(
        unattended_policy,
        "live_platform_maturities",
        lambda: {"lever": "dry_run", "generic": None},
    )

    user = User(
        email="qualification-probe@example.test",
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
            "auto_apply_min_score": 0.95,
            "auto_apply_daily_limit": 5,
            "auto_apply_weekly_limit": 20,
            "auto_apply_daily_per_employer_limit": 2,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
            "autopilot_employer_allow_list": ["Ottawa Only Employer"],
            "autopilot_employer_exclude_list": [],
            "autopilot_allowed_locations": ["ottawa"],
            "autopilot_min_salary": 150000,
            "autopilot_allowed_seniority": ["entry"],
            "autopilot_allowed_languages": ["english"],
        },
        job_preferences={"ats_targets": [dict(ATS_TARGET)]},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    job = Job(
        external_id="lever:eqbank:qualification-probe",
        title="Manager, AML Investigations",
        company="EQ Bank",
        location="Toronto",
        salary_min=70000,
        seniority="senior",
        source=JobSource.lever,
        status=JobStatus.queued,
        relevance_score=0.10,
        url="https://jobs.lever.co/eqbank/qualification-probe",
        raw_data={
            "selected_apply_url": "https://jobs.lever.co/eqbank/qualification-probe",
            "language": "french",
            "requires_sponsorship": False,
            "official_public_ats": True,
            "ats_provider": "lever",
        },
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(job)

    projection = canary._apply_only_scheduler_user(
        user,
        qualification_candidate_job_ids=[int(job.id)],
    )
    assert projection.automation_settings["auto_apply_min_score"] == 0.0
    assert user.automation_settings["auto_apply_min_score"] == 0.95
    assert projection._qualification_candidate_job_ids == (int(job.id),)

    qualification_session = _session(
        db_session,
        int(user.id),
        "shadow_qualification_canary",
        qualification=True,
    )
    with shadow_dry_run_policy_context(
        shadow_session_id=int(qualification_session.id),
        dry_run=True,
    ):
        qualification_decision = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            projection,
            job,
        )

    assert qualification_decision.allowed is True
    assert qualification_decision.code == "shadow_dry_run_maturity_exception"
    assert qualification_decision.metadata["shadow_qualification_probe"] is True
    assert qualification_decision.metadata["shadow_suitability_filters_bypassed"] is True

    qualification_session.status = "completed"
    db_session.commit()

    timed_session = _session(
        db_session,
        int(user.id),
        "shadow_run_4h",
        qualification=False,
    )
    with shadow_dry_run_policy_context(
        shadow_session_id=int(timed_session.id),
        dry_run=True,
    ):
        timed_decision = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            user,
            job,
        )

    assert timed_decision.allowed is True
    assert timed_decision.code == "shadow_dry_run_maturity_exception"
    assert timed_decision.metadata["shadow_qualification_probe"] is False
    assert timed_decision.metadata["shadow_suitability_filters_bypassed"] is True


def test_qualification_probe_requires_dry_run_and_real_submit_disabled(
    db_session,
    monkeypatch,
):
    operations = _operations()
    monkeypatch.setattr(operations_policy, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(unattended_policy, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(
        unattended_policy,
        "live_platform_maturities",
        lambda: {"lever": "dry_run", "generic": None},
    )

    user = User(
        email="qualification-probe-safety@example.test",
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "auto_apply_daily_limit": 5,
            "auto_apply_weekly_limit": 20,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
            "autopilot_allowed_locations": ["ottawa"],
        },
        is_active=True,
    )
    job = Job(
        external_id="lever:eqbank:qualification-safety",
        title="Fraud Officer",
        company="EQ Bank",
        location="Toronto",
        source=JobSource.lever,
        status=JobStatus.queued,
        relevance_score=1.0,
        url="https://jobs.lever.co/eqbank/qualification-safety",
        raw_data={
            "selected_apply_url": "https://jobs.lever.co/eqbank/qualification-safety",
            "official_public_ats": True,
        },
    )
    db_session.add_all([user, job])
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(job)
    session = _session(
        db_session,
        int(user.id),
        "shadow_qualification_canary",
        qualification=True,
    )

    monkeypatch.setattr(
        unattended_policy,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=False),
    )
    with shadow_dry_run_policy_context(
        shadow_session_id=int(session.id),
        dry_run=False,
    ):
        not_dry_run = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            user,
            job,
        )
    assert not_dry_run.allowed is False
    assert not_dry_run.metadata["shadow_qualification_probe"] is False

    monkeypatch.setattr(
        unattended_policy,
        "get_settings",
        lambda: SimpleNamespace(allow_real_application_submit=True),
    )
    with shadow_dry_run_policy_context(
        shadow_session_id=int(session.id),
        dry_run=True,
    ):
        real_submit_enabled = unattended_policy.evaluate_unattended_job_policy(
            db_session,
            user,
            job,
        )
    assert real_submit_enabled.allowed is False
    assert real_submit_enabled.metadata["shadow_qualification_probe"] is False
