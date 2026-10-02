from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.celery_app import celery_app
from app.models.intelligence import AgentRun
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.discovery_dedup import partition_new_discovery_jobs
from app.services.discovery_freshness_integration import (
    FRESHNESS_BLOCK_CODE,
    gate_ranked_candidates,
    install_scheduler_freshness_gate,
)
from app.services.discovery_scheduler import (
    DISCOVERY_FRESHNESS_TTL_HOURS,
    apply_source_backoff,
    job_freshness_evidence,
    source_backoff_status,
)
from app.services.operations_settings import get_operations_settings
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION
from app.tasks import discovery as discovery_tasks


def _user(db_session, *, email: str, auto_search: bool = True) -> User:
    user = User(
        email=email,
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "auto_search_enabled": auto_search,
            "auto_apply_enabled": False,
            "scheduler_search_keywords": ["Risk analyst"],
            "scheduler_search_location": "Ottawa, Ontario",
            "scheduler_search_sources": ["linkedin"],
        },
        job_preferences={
            "preferred_titles": ["Risk analyst"],
            "preferred_locations": ["Ottawa, Ontario"],
        },
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _diagnostic_run(db_session, user_id: int, *, status: str, completed_at: datetime) -> AgentRun:
    run = AgentRun(
        user_id=user_id,
        objective="continuous discovery health",
        status="completed",
        autonomy_level="reviewed",
        risk_level="low",
        requires_approval=False,
        plan=[],
        run_context={},
        result={
            "source_diagnostics": [
                {
                    "source": "linkedin",
                    "kind": "broad_board",
                    "status": status,
                    "target": None,
                    "result_count": 0,
                    "error_code": "http_error" if status == "failed" else None,
                }
            ]
        },
        started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
    )
    db_session.add(run)
    db_session.commit()
    return run


def test_continuous_discovery_runs_when_application_autopilot_is_off(
    db_session, monkeypatch
):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "false")
    get_operations_settings.cache_clear()
    user = _user(db_session, email="continuous-autopilot-off@example.test")
    queued = MagicMock()
    queued.id = "discovery-task-1"
    delay = MagicMock(return_value=queued)
    monkeypatch.setattr(discovery_tasks.run_job_search, "delay", delay)

    result = discovery_tasks._run_continuous_discovery(db_session)

    assert result["skipped"] is False
    assert result["autopilot_enabled"] is False
    assert result["searches_queued"] == 1
    assert result["cycles"][0]["user_id"] == user.id
    assert result["cycles"][0]["reason"] == "continuous_discovery_queued"
    kwargs = delay.call_args.kwargs
    assert kwargs["user_id"] == user.id
    assert kwargs["search_params"]["_origin"] == "scheduler"
    assert kwargs["search_params"]["sources"] == ["linkedin"]
    get_operations_settings.cache_clear()


def test_continuous_discovery_respects_global_kill_switch(db_session, monkeypatch):
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    get_operations_settings.cache_clear()
    _user(db_session, email="continuous-kill-switch@example.test")
    delay = MagicMock()
    monkeypatch.setattr(discovery_tasks.run_job_search, "delay", delay)

    result = discovery_tasks._run_continuous_discovery(db_session)

    assert result["skipped"] is True
    assert result["reason"] == "global_kill_switch"
    assert result["searches_queued"] == 0
    delay.assert_not_called()
    get_operations_settings.cache_clear()


def test_source_backoff_is_exponential_and_a_success_resets_it(db_session):
    user = _user(db_session, email="source-backoff@example.test")
    now = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)
    _diagnostic_run(db_session, user.id, status="failed", completed_at=now - timedelta(minutes=6))
    _diagnostic_run(db_session, user.id, status="failed", completed_at=now - timedelta(minutes=5))

    failed = source_backoff_status(
        db_session,
        user_id=user.id,
        source="linkedin",
        kind="broad_board",
        now=now,
    )
    assert failed["consecutive_failures"] == 2
    assert failed["cooldown_seconds"] == 30 * 60
    assert failed["blocked"] is True

    _diagnostic_run(db_session, user.id, status="success", completed_at=now - timedelta(minutes=1))
    recovered = source_backoff_status(
        db_session,
        user_id=user.id,
        source="linkedin",
        kind="broad_board",
        now=now,
    )
    assert recovered["last_status"] == "success"
    assert recovered["consecutive_failures"] == 0
    assert recovered["blocked"] is False


def test_source_backoff_filters_only_unhealthy_sources(db_session):
    user = _user(db_session, email="source-filter@example.test")
    now = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)
    _diagnostic_run(db_session, user.id, status="failed", completed_at=now - timedelta(minutes=1))

    bounded = apply_source_backoff(
        db_session,
        user_id=user.id,
        now=now,
        search_params={
            "keywords": "Risk analyst",
            "location": "Ottawa, Ontario",
            "sources": ["linkedin", "lever"],
            "ats_targets": [
                {"provider": "lever", "identifier": "acme", "company": "Acme"}
            ],
            "limit": 50,
        },
    )

    assert bounded["ready"] is True
    assert bounded["search_params"]["sources"] == ["lever"]
    assert len(bounded["search_params"]["ats_targets"]) == 1
    assert len(bounded["blocked_sources"]) == 1
    assert bounded["blocked_sources"][0]["source"] == "linkedin"


def test_discovery_freshness_expires_after_72_hours():
    now = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)
    fresh = Job(
        id=1,
        title="Fresh role",
        company="Acme",
        source=JobSource.lever,
        raw_data={"discovery_last_seen_at": (now - timedelta(hours=72)).isoformat()},
    )
    stale = Job(
        id=2,
        title="Stale role",
        company="Acme",
        source=JobSource.lever,
        raw_data={"discovery_last_seen_at": (now - timedelta(hours=72, seconds=1)).isoformat()},
    )

    fresh_evidence = job_freshness_evidence(fresh, now=now)
    stale_evidence = job_freshness_evidence(stale, now=now)
    assert fresh_evidence["ttl_hours"] == DISCOVERY_FRESHNESS_TTL_HOURS
    assert fresh_evidence["fresh"] is True
    assert stale_evidence["fresh"] is False
    assert stale_evidence["reason"] == "freshness_expired"


def test_freshness_gate_blocks_stale_discovered_candidate_but_not_manual_job():
    now = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)
    stale = Job(
        id=10,
        title="Stale Lever role",
        company="Acme",
        source=JobSource.lever,
        raw_data={"discovery_last_seen_at": (now - timedelta(days=4)).isoformat()},
    )
    manual = Job(
        id=11,
        title="Owner supplied role",
        company="Acme",
        source=JobSource.manual,
        raw_data={},
    )
    ranked = [
        {
            "job": stale,
            "priority_score": 99.0,
            "priority_evidence": {},
            "decision": {"allowed": True, "code": "allowed", "reason": "allowed", "metadata": {}},
        },
        {
            "job": manual,
            "priority_score": 80.0,
            "priority_evidence": {},
            "decision": {"allowed": True, "code": "allowed", "reason": "allowed", "metadata": {}},
        },
    ]

    gated = gate_ranked_candidates(ranked, now=now)

    assert gated[0]["job"].id == manual.id
    stale_result = next(item for item in gated if item["job"].id == stale.id)
    assert stale_result["decision"]["allowed"] is False
    assert stale_result["decision"]["code"] == FRESHNESS_BLOCK_CODE


def test_worker_freshness_installer_wraps_scraping_ranker_once(monkeypatch):
    from app.tasks import scraping

    observed = {}

    def fake_ranker(db, user, *, limit=20, now=None):
        observed["limit"] = limit
        return []

    monkeypatch.setattr(scraping, "rank_scheduler_candidates", fake_ranker)
    install_scheduler_freshness_gate()
    wrapped = scraping.rank_scheduler_candidates
    assert getattr(wrapped, "_jobtomatik_discovery_freshness_gate", False) is True

    wrapped(None, None, limit=7)
    assert observed["limit"] == 35

    install_scheduler_freshness_gate()
    assert scraping.rank_scheduler_candidates is wrapped


def test_cross_board_dedup_uses_exact_employer_apply_url(db_session):
    existing = Job(
        external_id="lever:acme:posting-123",
        title="Risk analyst",
        company="Acme",
        location="Ottawa, ON",
        source=JobSource.lever,
        status=JobStatus.queued,
        url="https://jobs.lever.co/acme/posting-123",
        raw_data={"official_public_ats": True},
    )
    db_session.add(existing)
    db_session.commit()

    jobbank_copy = {
        "external_id": "jobbank-volatile-1",
        "title": "Risk analyst",
        "company": "Acme",
        "location": "Ottawa, ON",
        "source": "jobbank",
        "url": "https://www.jobbank.gc.ca/jobsearch/jobposting/12345678",
        "raw_data": {
            "jobbank_original_url": "https://www.jobbank.gc.ca/jobsearch/jobposting/12345678",
            "selected_apply_url": "https://jobs.lever.co/acme/posting-123?lever-source=jobbank",
        },
    }

    prepared, collapsed = partition_new_discovery_jobs(db_session, [jobbank_copy])

    assert collapsed == 0
    assert len(prepared) == 1
    assert prepared[0]["external_id"] == existing.external_id
    assert prepared[0]["raw_data"]["discovery_first_seen_at"]
    assert prepared[0]["raw_data"]["discovery_last_seen_at"]


def test_celery_beat_declares_hourly_continuous_discovery():
    schedule = celery_app.conf.beat_schedule["continuous-job-discovery-hourly"]
    assert schedule["task"] == "app.tasks.discovery.run_continuous_discovery"
    assert "app.tasks.discovery" in celery_app.conf.include
    assert celery_app.conf.task_routes["app.tasks.discovery.*"]["queue"] == "scraping"
