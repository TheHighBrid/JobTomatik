from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import sessionmaker

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.certification import ShadowRunSession
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.operations_settings import OperationsSettings
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION
from app.tasks import applications, scraping, unattended
from app.services import operations_policy, scheduler_policy, shadow_qualification, unattended_policy
from scripts import run_shadow_qualification_canary as canary


REVISION = "7" * 40


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


def test_qualification_canary_wires_real_policy_scheduler_application_and_worker_once(
    db_session,
    monkeypatch,
    tmp_path,
):
    """Exercise the production qualification call tree with dirty persistent queue state.

    GitHub cannot perform the physical Android/CDP proof, but it can prove that the
    qualification command composes the real policy, scheduler, durable Application
    evidence, worker-side shadow recheck, and dry-run terminal contract. The database
    deliberately contains older uncertified generic candidates ahead of the newly
    discovered Lever job, reproducing the physical Campaign #2 failure class. The
    qualification Application must still bind to the exact discovery cohort rather
    than whichever stale rows happen to appear first in the global queue.
    """

    local_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.get_bind(),
    )
    user = User(
        email="qualification-contract@example.test",
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
            "auto_apply_min_score": 0.65,
            "auto_apply_daily_limit": 5,
            "auto_apply_weekly_limit": 20,
            "auto_apply_daily_per_employer_limit": 2,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
            "scheduler_search_keywords": ["risk analyst"],
            "scheduler_search_location": "Ottawa, ON",
            "scheduler_search_sources": ["lever"],
        },
        job_preferences={
            "ats_targets": [
                {
                    "provider": "lever",
                    "identifier": "qualification-contract",
                    "company": "Qualification Contract Co",
                }
            ]
        },
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    # Persistent dirty-state reproduction: without exact discovery binding these rows
    # occupy the scheduler's first candidate window and all fail platform maturity.
    for index in range(6):
        db_session.add(
            Job(
                external_id=f"stale-uncertified-{index}",
                title=f"Legacy queued role {index}",
                company=f"Legacy Company {index}",
                location="ottawa, ontario",
                source=JobSource.manual,
                status=JobStatus.queued,
                relevance_score=1.0,
                url=f"https://example.com/jobs/legacy-{index}",
                raw_data={"application_method": "manual"},
            )
        )
    db_session.commit()
    user_id = int(user.id)

    operations = _operations()
    for module in (
        operations_policy,
        scheduler_policy,
        shadow_qualification,
        unattended_policy,
    ):
        monkeypatch.setattr(module, "get_operations_settings", lambda: operations)

    core = SimpleNamespace(
        allow_real_application_submit=False,
        allow_real_followup_send=False,
    )
    monkeypatch.setattr(canary, "get_settings", lambda: core)
    monkeypatch.setattr(unattended, "get_settings", lambda: core)
    monkeypatch.setattr(scraping, "settings", core)
    maturity_map = {
        "greenhouse": "dry_run",
        "lever": "dry_run",
        "ashby": "dry_run",
        "smartrecruiters": "dry_run",
        "workday": "dry_run",
        "generic": None,
    }
    monkeypatch.setattr(
        unattended_policy,
        "live_platform_maturities",
        lambda: dict(maturity_map),
    )
    monkeypatch.setattr(
        shadow_qualification,
        "live_platform_maturities",
        lambda: dict(maturity_map),
    )

    monkeypatch.setattr(canary, "current_revision", lambda: REVISION)
    monkeypatch.setattr(
        canary,
        "runtime_acceptance_status",
        lambda: {"ok": True, "blockers": [], "revision": REVISION},
    )
    monkeypatch.setattr(
        canary,
        "runtime_fingerprint",
        lambda: {"sha256": "f" * 64, "revision": REVISION},
    )
    monkeypatch.setattr(canary, "SessionLocal", local_session)
    monkeypatch.setattr(unattended, "SessionLocal", local_session)
    receipt_path = tmp_path / "shadow-qualification-canary.json"
    monkeypatch.setattr(canary, "canary_receipt_path", lambda _user_id: receipt_path)

    discovery_calls: list[dict] = []

    class DiscoveryResult:
        def __init__(self, kwargs):
            self.kwargs = kwargs

        def get(self, timeout, propagate):
            assert timeout == 120
            assert propagate is True
            params = dict(self.kwargs["search_params"])
            session_id = int(params["_shadow_session_id"])
            with local_session() as db:
                discovered_job = Job(
                    external_id=f"qualification-contract-{session_id}",
                    title="Risk Analyst",
                    company="Qualification Contract Co",
                    location="ottawa, ontario",
                    salary_min=90000,
                    seniority="mid",
                    source=JobSource.lever,
                    status=JobStatus.queued,
                    relevance_score=0.99,
                    url="https://jobs.lever.co/qualification-contract/risk-analyst",
                    raw_data={
                        "language": "english",
                        "requires_sponsorship": False,
                        "application_method": "lever",
                    },
                )
                db.add(discovered_job)
                db.flush()
                discovered_job_id = int(discovered_job.id)
                db.commit()
            return {
                "total_found": 1,
                "saved": 1,
                "new_candidates": 1,
                "duplicates": 0,
                "job_ids": [discovered_job_id],
                "origin": "scheduler",
                "shadow_session_id": session_id,
            }

        def forget(self):
            return None

    def fake_discovery_apply_async(*, kwargs, queue):
        assert queue == "scraping"
        assert kwargs["user_id"] == user_id
        assert kwargs["search_params"]["ats_targets"] == [
            {
                "provider": "lever",
                "identifier": "qualification-contract",
                "company": "Qualification Contract Co",
            }
        ]
        discovery_calls.append(kwargs)
        return DiscoveryResult(kwargs)

    monkeypatch.setattr(canary.run_job_search, "apply_async", fake_discovery_apply_async)
    duplicate_scheduler_search = MagicMock()
    monkeypatch.setattr(scraping.run_job_search, "delay", duplicate_scheduler_search)

    monkeypatch.setattr(
        applications.generate_cover_letter_task,
        "delay",
        lambda application_id: SimpleNamespace(id=f"cover-{application_id}"),
    )

    worker_dispatches: list[dict] = []

    def capture_worker_dispatch(*, args, kwargs, countdown):
        worker_dispatches.append(
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
        capture_worker_dispatch,
    )

    def fake_browser_dry_run(application_id: int, dry_run: bool = True):
        assert dry_run is True
        with local_session() as db:
            app = db.query(Application).filter(Application.id == int(application_id)).one()
            app.submission_attempt_count = 1
            app.status = ApplicationStatus.pending
            app.automation_state = ApplicationAutomationState.ready_to_apply.value
            app.automation_log = [
                {"action": "navigate"},
                {"action": "ats_adapter_detected"},
                {"action": "ats_final_submit_ready", "submit_clicked": False},
            ]
            db.add(
                ApplicationEvent(
                    application_id=app.id,
                    event_type="dry_run_completed",
                    from_state=ApplicationAutomationState.preparing.value,
                    to_state=ApplicationAutomationState.ready_to_apply.value,
                    payload={"dry_run": True, "submit_clicked": False},
                )
            )
            db.commit()
        return {"success": True, "dry_run": True, "submit_clicked": False}

    monkeypatch.setattr(applications.submit_application_task, "run", fake_browser_dry_run)

    original_wait = canary._wait_for_application_path

    def run_worker_then_wait(db, application_id, session_id, timeout_seconds):
        assert len(worker_dispatches) == 1
        dispatch = worker_dispatches[0]
        assert dispatch["countdown"] == 120
        assert dispatch["args"] == [application_id]
        assert dispatch["kwargs"] == {
            "dry_run": True,
            "shadow_session_id": session_id,
        }
        worker_result = unattended.submit_unattended_application_task.run(
            application_id,
            dry_run=True,
            shadow_session_id=session_id,
        )
        assert worker_result["success"] is True
        assert worker_result["dry_run"] is True
        return original_wait(db, application_id, session_id, max(1, timeout_seconds))

    monkeypatch.setattr(canary, "_wait_for_application_path", run_worker_then_wait)

    receipt = canary.run_canary(
        requested_user_id=user_id,
        timeout_seconds=2,
    )

    assert receipt["status"] == "pass"
    assert receipt["type"] == "shadow_qualification_canary"
    assert receipt["revision"] == REVISION
    assert receipt["application_path_observed"] is True
    assert receipt["certification_eligible"] is False
    assert receipt["safety"] == {
        "real_submission_disabled": True,
        "final_submit_allowed": False,
        "outreach_authorized": False,
        "adapter_maturity_mutated": False,
        "consequential_state_observed": False,
    }
    assert receipt["scheduler_result"]["applications_queued"] == 1
    assert receipt["scheduler_result"]["searched"] is False
    assert receipt["scheduler_result"]["dry_run"] is True
    assert receipt["scheduler_application_bound_to_discovery"] is True
    assert receipt["application"]["job_id"] in receipt["discovery_job_ids"]
    assert receipt["application"]["dry_run_completed"] is True
    assert receipt["application"]["browser_or_form_path_observed"] is True
    assert receipt["application"]["safe_terminal"] is True
    assert receipt["application"]["consequential_state_observed"] is False
    assert receipt["post_canary_policy"]["ok"] is True
    assert receipt["post_canary_policy"]["remaining_daily"] >= 1
    assert receipt["post_canary_policy"]["remaining_weekly"] >= 1

    assert len(discovery_calls) == 1
    duplicate_scheduler_search.assert_not_called()
    assert len(worker_dispatches) == 1

    with local_session() as db:
        session = db.query(ShadowRunSession).filter(ShadowRunSession.user_id == user_id).one()
        assert session.status == "completed"
        assert session.target_evidence_type == "shadow_qualification_canary"
        assert session.final_submit_allowed is False
        assert session.final_report["certification_eligible"] is False
        assert session.final_report["scheduler_application_bound_to_discovery"] is True

        app = db.query(Application).filter(Application.user_id == user_id).one()
        assert int(app.job_id) in receipt["discovery_job_ids"]
        created = (
            db.query(ApplicationEvent)
            .filter(
                ApplicationEvent.application_id == app.id,
                ApplicationEvent.event_type == "application_created",
            )
            .one()
        )
        assert created.payload["source"] == "full_stack_shadow_scheduler"
        assert created.payload["dry_run"] is True
        assert int(created.payload["shadow_session_id"]) == int(session.id)


def test_quiet_hours_do_not_fabricate_zero_capacity_blockers(db_session, monkeypatch):
    operations = OperationsSettings(
        global_kill_switch=False,
        autopilot_enabled=True,
        default_daily_cap=5,
        default_weekly_cap=20,
        quiet_hours_start_utc=0,
        quiet_hours_end_utc=6,
        failure_threshold=3,
        failure_window_minutes=60,
        circuit_breaker_minutes=120,
        stale_attempt_minutes=30,
        disabled_platforms="",
    )
    for module in (operations_policy, scheduler_policy, shadow_qualification):
        monkeypatch.setattr(module, "get_operations_settings", lambda: operations)

    user = User(
        email="quiet-capacity@example.test",
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 6,
        },
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    readiness = shadow_qualification.campaign_policy_readiness(
        db_session,
        user,
        requested_duration_seconds=4 * 60 * 60,
        required_remaining_applications=2,
        now=datetime(2026, 8, 13, 1, 0, 0),
    )

    assert readiness["autopilot_decision"]["code"] == "quiet_hours"
    assert readiness["daily_capacity_evaluated"] is False
    assert readiness["weekly_capacity_evaluated"] is False
    assert readiness["remaining_daily"] is None
    assert readiness["remaining_weekly"] is None
    assert readiness["checks"]["daily_capacity_headroom"] is True
    assert readiness["checks"]["weekly_capacity_headroom"] is True
    assert "daily_capacity_headroom" not in readiness["blockers"]
    assert "weekly_capacity_headroom" not in readiness["blockers"]
    assert "autopilot_policy_currently_allowed" in readiness["blockers"]
    assert "quiet_hours_clear_for_requested_window" in readiness["blockers"]
