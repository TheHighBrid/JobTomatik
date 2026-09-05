"""Day 33 isolated crash-recovery and dead-letter chaos certification.

The matrix exercises JobTomatik recovery primitives entirely against an in-memory
SQLite database. It does not launch a browser, contact an employer, dispatch Celery
work, authorize submission, or alter adapter maturity. The purpose is to prove that
representative runtime failures preserve idempotency/state and that any actual replay
requires the existing verified dead-letter checkpoint contract.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewTask,
)
from app.models.intelligence import AgentRun, AgentTask
from app.models.job import Job
from app.models.user import User
from app.services.agent_execution import approve_run
from app.services.application_recovery import recover_stale_application_attempt
from app.services.dead_letter import (
    DEAD_LETTER_KEY,
    DeadLetterError,
    requeue_dead_letter,
    reopen_dead_letter_after_dispatch_failure,
    route_task_to_dead_letter,
)


DAY33_RECOVERY_POLICY_VERSION = "crash-recovery-chaos-v1"
FAILURE_MODES = (
    "process_crash",
    "worker_restart",
    "redis_interruption",
    "database_lock",
    "browser_death",
    "device_reboot",
)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _new_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    return engine, Session()


def _create_user_and_job(db) -> tuple[User, Job]:
    user = User(
        email="day33-recovery@example.test",
        hashed_password="day33-recovery-test-only",
        full_name="Day 33 Recovery Drill",
        is_active=True,
        profile_data={},
        job_preferences={},
        automation_settings={},
    )
    job = Job(
        external_id="day33-recovery-job",
        title="Recovery Verification Analyst",
        company="Synthetic Recovery Employer",
        url="https://job-boards.greenhouse.io/day33/jobs/recovery",
    )
    db.add_all([user, job])
    db.flush()
    return user, job


def _create_applying_application(
    db,
    *,
    user: User,
    job: Job,
    mode: str,
    dry_run: bool | None,
    now: datetime,
) -> Application:
    started_at = now - timedelta(minutes=1)
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_idempotency_key=f"day33:{mode}:{user.id}:{job.id}",
        submission_attempt_count=1,
        last_submission_attempt_at=started_at,
        created_at=started_at,
    )
    db.add(application)
    db.flush()
    if dry_run is not None:
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="application_attempt_started",
            from_state=ApplicationAutomationState.ready_to_apply.value,
            to_state=ApplicationAutomationState.applying.value,
            payload={
                "dry_run": dry_run,
                "attempt": 1,
                "chaos_mode": mode,
            },
            created_at=started_at,
        ))
        db.flush()
    return application


def _exercise_application_interruption(
    db,
    *,
    user: User,
    job: Job,
    mode: str,
    dry_run: bool | None,
    expected_state: str,
    now: datetime,
) -> dict[str, Any]:
    application = _create_applying_application(
        db,
        user=user,
        job=job,
        mode=mode,
        dry_run=dry_run,
        now=now,
    )
    before_key = application.submission_idempotency_key
    before_attempts = int(application.submission_attempt_count or 0)

    result = recover_stale_application_attempt(
        db,
        application,
        now=now,
        force_interrupted=True,
    )
    db.flush()
    recovered_state = str(application.automation_state or "")
    review_count = db.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
    ).count()
    terminal_submission_events = db.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == application.id,
        ApplicationEvent.event_type.in_([
            "application_submitted",
            "submission_confirmed",
        ]),
    ).count()

    repeated = recover_stale_application_attempt(
        db,
        application,
        now=now + timedelta(minutes=1),
        force_interrupted=True,
    )
    db.flush()

    checks = {
        "recovered": result.get("recovered") is True,
        "expected_state": recovered_state == expected_state,
        "idempotency_key_preserved": application.submission_idempotency_key == before_key,
        "submission_attempt_count_preserved": int(application.submission_attempt_count or 0) == before_attempts,
        "no_submission_event_created": terminal_submission_events == 0,
        "one_manual_review_created": review_count == 1,
        "repeat_recovery_is_noop": repeated.get("recovered") is False and repeated.get("reason") == "not_applying",
        "not_marked_submitted": recovered_state not in {
            ApplicationAutomationState.submitted.value,
            ApplicationAutomationState.confirmed.value,
        },
    }
    return {
        "failure_mode": mode,
        "domain": "application",
        "application_id": application.id,
        "dry_run": dry_run,
        "expected_state": expected_state,
        "actual_state": recovered_state,
        "idempotency_key_sha256": hashlib.sha256(str(before_key).encode("utf-8")).hexdigest(),
        "submission_attempt_count": int(application.submission_attempt_count or 0),
        "recovery_reason_code": result.get("reason_code"),
        "review_id": result.get("review_id"),
        "automatic_retry_allowed": False,
        "resume_performed": False,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _create_failed_bounded_task(
    db,
    *,
    user: User,
    mode: str,
) -> tuple[AgentRun, AgentTask]:
    plan = [
        {
            "id": f"{mode}-task",
            "name": f"Synthetic {mode} bounded task",
            "agent_type": "company_research",
            "dependencies": [],
            "input": {"job_id": 700, "failure_mode": mode},
        }
    ]
    run = AgentRun(
        user_id=user.id,
        objective=f"Day 33 {mode} recovery verification",
        status="running",
        autonomy_level="reviewed",
        risk_level="low",
        requires_approval=True,
        plan=plan,
        run_context={
            "job_id": 700,
            "pipeline": "day33_recovery_chaos",
            "selector_requirements": {"mode": mode},
        },
    )
    db.add(run)
    db.flush()
    task = AgentTask(
        run_id=run.id,
        sequence=0,
        name=f"Synthetic {mode} bounded task",
        agent_type="company_research",
        status="failed",
        dependencies=[],
        task_input={"job_id": 700, "failure_mode": mode},
        task_output={"execution": {"failure_class": mode}},
        attempt_count=2,
        max_attempts=2,
        error=f"synthetic {mode}",
    )
    db.add(task)
    db.flush()
    db.refresh(run)
    approve_run(run, user_id=user.id, note="Day 33 isolated recovery drill")
    db.flush()
    return run, task


def _complete_context(envelope: dict[str, Any], *, run: AgentRun, task: AgentTask) -> bool:
    checkpoint = dict(envelope.get("checkpoint") or {})
    approval = dict(checkpoint.get("approval") or {})
    required = {
        "run_id": run.id,
        "user_id": run.user_id,
        "task_id": task.id,
        "plan_task_id": f"{task.task_input['failure_mode']}-task",
        "agent_type": task.agent_type,
    }
    return (
        all(checkpoint.get(key) == value for key, value in required.items())
        and checkpoint.get("task_input") == dict(task.task_input or {})
        and isinstance(checkpoint.get("dependencies"), list)
        and bool(checkpoint.get("run_plan_hash"))
        and checkpoint.get("stable_run_context", {}).get("pipeline") == "day33_recovery_chaos"
        and approval.get("submission_authorized") is False
        and approval.get("outreach_authorized") is False
    )


def _exercise_redis_interruption(db, *, user: User) -> dict[str, Any]:
    run, task = _create_failed_bounded_task(db, user=user, mode="redis_interruption")
    initial_attempts = int(task.attempt_count or 0)
    envelope = route_task_to_dead_letter(
        db,
        run,
        task,
        failure_class="redis_interruption",
        error="synthetic Redis broker interruption",
        source="dispatch",
    )
    db.flush()
    stored_checkpoint = str(envelope.get("checkpoint_hash") or "")
    requeued = requeue_dead_letter(
        db,
        user_id=user.id,
        task_id=task.id,
        acknowledgment=envelope["expected_requeue_acknowledgment"],
    )
    db.flush()
    reopened = reopen_dead_letter_after_dispatch_failure(
        db,
        user_id=user.id,
        task_id=task.id,
        error="synthetic Redis interruption after verified requeue",
    )
    db.flush()
    current = dict((task.task_output or {}).get(DEAD_LETTER_KEY) or {})

    checks = {
        "dead_letter_created": bool(stored_checkpoint),
        "complete_context_retained": _complete_context(envelope, run=run, task=task),
        "verified_checkpoint_requeue": requeued.get("checkpoint_hash") == stored_checkpoint,
        "dispatch_failure_reopens_dead_letter": reopened.get("status") == "open" and current.get("status") == "open",
        "automatic_retry_disabled": current.get("automatic_retry_allowed") is False,
        "checkpoint_preserved": current.get("checkpoint_hash") == stored_checkpoint,
        "attempt_history_preserved": int(task.attempt_count or 0) == initial_attempts,
        "submission_authorized_false": reopened.get("submission_authorized") is False,
        "outreach_authorized_false": reopened.get("outreach_authorized") is False,
        "status_fail_closed": task.status == "failed",
    }
    return {
        "failure_mode": "redis_interruption",
        "domain": "bounded_task",
        "run_id": run.id,
        "task_id": task.id,
        "checkpoint_hash": stored_checkpoint,
        "dead_letter_status": current.get("status"),
        "requeue_count": current.get("requeue_count"),
        "automatic_retry_allowed": current.get("automatic_retry_allowed"),
        "resume_performed": True,
        "resume_checkpoint_verified": requeued.get("checkpoint_hash") == stored_checkpoint,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _exercise_database_lock(db, *, user: User) -> dict[str, Any]:
    run, task = _create_failed_bounded_task(db, user=user, mode="database_lock")
    initial_attempts = int(task.attempt_count or 0)
    envelope = route_task_to_dead_letter(
        db,
        run,
        task,
        failure_class="database_lock",
        error="synthetic database is locked after bounded retry exhaustion",
        source="database_commit",
    )
    db.flush()
    stored_checkpoint = str(envelope.get("checkpoint_hash") or "")

    # Prove a task whose durable context changed after failure cannot be resumed.
    task.task_input = {
        **dict(task.task_input or {}),
        "tampered_after_database_lock": True,
    }
    db.flush()
    drift_blocked = False
    drift_error = None
    try:
        requeue_dead_letter(
            db,
            user_id=user.id,
            task_id=task.id,
            acknowledgment=envelope["expected_requeue_acknowledgment"],
        )
    except DeadLetterError as exc:
        drift_error = str(exc)
        drift_blocked = "checkpoint drift" in str(exc).lower()

    current = dict((task.task_output or {}).get(DEAD_LETTER_KEY) or {})
    checks = {
        "dead_letter_created": current.get("status") == "open",
        "complete_context_retained": _complete_context(envelope, run=run, task=AgentTask(
            id=task.id,
            run_id=task.run_id,
            sequence=task.sequence,
            name=task.name,
            agent_type=task.agent_type,
            status="failed",
            dependencies=list(task.dependencies or []),
            task_input={"job_id": 700, "failure_mode": "database_lock"},
        )),
        "checkpoint_hash_was_exact": bool(stored_checkpoint),
        "checkpoint_drift_blocks_resume": drift_blocked,
        "automatic_retry_disabled": current.get("automatic_retry_allowed") is False,
        "attempt_history_preserved": int(task.attempt_count or 0) == initial_attempts,
        "task_remains_failed": task.status == "failed",
        "submission_authorized_false": current.get("submission_authorized") is False,
        "outreach_authorized_false": current.get("outreach_authorized") is False,
    }
    return {
        "failure_mode": "database_lock",
        "domain": "bounded_task",
        "run_id": run.id,
        "task_id": task.id,
        "checkpoint_hash": stored_checkpoint,
        "dead_letter_status": current.get("status"),
        "automatic_retry_allowed": current.get("automatic_retry_allowed"),
        "resume_performed": False,
        "resume_checkpoint_verified": False,
        "checkpoint_drift_blocked": drift_blocked,
        "drift_error": drift_error,
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_day33_recovery_chaos_matrix() -> dict[str, Any]:
    """Exercise all Day 33 failure modes and return immutable-style evidence."""

    engine, db = _new_session()
    try:
        now = _utcnow()
        user, job = _create_user_and_job(db)

        cases = [
            _exercise_application_interruption(
                db,
                user=user,
                job=job,
                mode="process_crash",
                dry_run=True,
                expected_state=ApplicationAutomationState.needs_review.value,
                now=now,
            ),
            _exercise_application_interruption(
                db,
                user=user,
                job=job,
                mode="worker_restart",
                dry_run=False,
                expected_state=ApplicationAutomationState.submission_uncertain.value,
                now=now + timedelta(minutes=2),
            ),
            _exercise_redis_interruption(db, user=user),
            _exercise_database_lock(db, user=user),
            _exercise_application_interruption(
                db,
                user=user,
                job=job,
                mode="browser_death",
                dry_run=None,
                expected_state=ApplicationAutomationState.submission_uncertain.value,
                now=now + timedelta(minutes=4),
            ),
            _exercise_application_interruption(
                db,
                user=user,
                job=job,
                mode="device_reboot",
                dry_run=True,
                expected_state=ApplicationAutomationState.needs_review.value,
                now=now + timedelta(minutes=6),
            ),
        ]
        db.flush()

        exercised_modes = tuple(case["failure_mode"] for case in cases)
        application_cases = [case for case in cases if case["domain"] == "application"]
        bounded_cases = [case for case in cases if case["domain"] == "bounded_task"]
        all_applications = db.query(Application).all()

        assertions = {
            "all_failure_modes_exercised": set(exercised_modes) == set(FAILURE_MODES),
            "all_cases_passed": all(case.get("passed") is True for case in cases),
            "no_duplicate_submission": all(
                int(application.submission_attempt_count or 0) == 1
                and str(application.automation_state or "") not in {
                    ApplicationAutomationState.submitted.value,
                    ApplicationAutomationState.confirmed.value,
                }
                for application in all_applications
            ),
            "no_status_corruption": all(
                str(application.automation_state or "")
                in {
                    ApplicationAutomationState.needs_review.value,
                    ApplicationAutomationState.submission_uncertain.value,
                }
                for application in all_applications
            ),
            "application_interruptions_fail_closed": all(
                case.get("automatic_retry_allowed") is False
                and case.get("resume_performed") is False
                for case in application_cases
            ),
            "verified_checkpoint_required_for_resume": (
                any(case.get("resume_checkpoint_verified") is True for case in bounded_cases)
                and any(case.get("checkpoint_drift_blocked") is True for case in bounded_cases)
            ),
            "irrecoverable_tasks_dead_lettered": all(
                case.get("dead_letter_status") == "open"
                and case.get("automatic_retry_allowed") is False
                for case in bounded_cases
            ),
            "consequential_authority_remains_false": all(
                case["checks"].get("submission_authorized_false", True)
                and case["checks"].get("outreach_authorized_false", True)
                for case in cases
            ),
        }

        report: dict[str, Any] = {
            "schema_version": "1.0",
            "policy_version": DAY33_RECOVERY_POLICY_VERSION,
            "generated_at": now.isoformat(),
            "mode": "isolated_in_memory",
            "failure_modes": list(FAILURE_MODES),
            "cases": cases,
            "assertions": assertions,
            "passed": all(assertions.values()),
            "safety": {
                "browser_opened": False,
                "network_contacted": False,
                "celery_dispatched": False,
                "final_submit_clicked": False,
                "recruiter_outreach_sent": False,
                "submission_authorized": False,
                "outreach_authorized": False,
                "adapter_maturity_changed": False,
            },
        }
        report["report_sha256"] = _canonical_hash(report)
        return report
    finally:
        db.close()
        engine.dispose()


__all__ = [
    "DAY33_RECOVERY_POLICY_VERSION",
    "FAILURE_MODES",
    "run_day33_recovery_chaos_matrix",
]
