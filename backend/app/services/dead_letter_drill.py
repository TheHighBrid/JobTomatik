"""Isolated dead-letter and checkpoint-resume certification drill.

The drill runs entirely in an in-memory SQLite database. It never launches a browser,
contacts an employer, sends recruiter outreach, or changes runtime feature flags.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.intelligence import AgentRun, AgentTask
from app.models.user import User
from app.services.agent_execution import approve_run
from app.services.dead_letter import (
    DeadLetterError,
    requeue_dead_letter,
    route_task_to_dead_letter,
)


DRILL_VERSION = "1.0.0"


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _create_run(db, user: User, *, suffix: str) -> tuple[AgentRun, AgentTask]:
    plan = [
        {
            "id": "primary",
            "name": "Synthetic bounded task",
            "agent_type": "company_research",
            "dependencies": [],
            "input": {"job_id": 100 + len(suffix)},
        }
    ]
    run = AgentRun(
        user_id=user.id,
        objective=f"Dead-letter recovery drill {suffix}",
        status="running",
        autonomy_level="reviewed",
        risk_level="low",
        requires_approval=True,
        plan=plan,
        run_context={"job_id": 100 + len(suffix)},
    )
    db.add(run)
    db.flush()
    task = AgentTask(
        run_id=run.id,
        sequence=0,
        name="Synthetic bounded task",
        agent_type="company_research",
        status="failed",
        dependencies=[],
        task_input={"job_id": 100 + len(suffix)},
        task_output={"execution": {"failure_class": "worker_exception"}},
        attempt_count=2,
        max_attempts=2,
        error="synthetic exhausted worker failure",
    )
    db.add(task)
    db.flush()
    db.refresh(run)
    approve_run(run, user_id=user.id, note="dead-letter drill only")
    db.flush()
    return run, task


def run_dead_letter_recovery_drill(
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="dead-letter-drill@example.test",
            hashed_password="dead-letter-drill",
            full_name="Dead Letter Drill",
            is_active=True,
        )
        db.add(user)
        db.flush()

        resumable_run, resumable_task = _create_run(db, user, suffix="resumable")
        envelope = route_task_to_dead_letter(
            db,
            resumable_run,
            resumable_task,
            failure_class="attempt_limit_reached",
            error=resumable_task.error,
            source="certification_drill",
        )
        original_attempt_count = resumable_task.attempt_count
        requeued = requeue_dead_letter(
            db,
            user_id=user.id,
            task_id=resumable_task.id,
            acknowledgment=envelope["expected_requeue_acknowledgment"],
        )

        drift_run, drift_task = _create_run(db, user, suffix="drift")
        drift_envelope = route_task_to_dead_letter(
            db,
            drift_run,
            drift_task,
            failure_class="attempt_limit_reached",
            error=drift_task.error,
            source="certification_drill",
        )
        drift_task.task_input = {"job_id": 999, "tampered_after_failure": True}
        db.flush()
        drift_blocked = False
        drift_error = None
        try:
            requeue_dead_letter(
                db,
                user_id=user.id,
                task_id=drift_task.id,
                acknowledgment=drift_envelope["expected_requeue_acknowledgment"],
            )
        except DeadLetterError as exc:
            drift_blocked = "checkpoint drift" in str(exc).lower()
            drift_error = str(exc)

        assertions = {
            "dead_letter_created": envelope.get("status") == "open",
            "automatic_retry_disabled": envelope.get("automatic_retry_allowed") is False,
            "verified_checkpoint_requeue": (
                requeued.get("status") == "pending"
                and resumable_task.status == "pending"
            ),
            "attempt_history_preserved": resumable_task.attempt_count == original_attempt_count,
            "exactly_one_additional_attempt_granted": (
                resumable_task.max_attempts == original_attempt_count + 1
            ),
            "checkpoint_drift_blocked": drift_blocked,
            "drift_task_remains_failed": drift_task.status == "failed",
            "submission_authorized_false": (
                requeued.get("submission_authorized") is False
                and envelope.get("submission_authorized") is False
            ),
            "outreach_authorized_false": (
                requeued.get("outreach_authorized") is False
                and envelope.get("outreach_authorized") is False
            ),
        }
        report: dict[str, Any] = {
            "version": DRILL_VERSION,
            "mode": "isolated_in_memory",
            "passed": all(assertions.values()),
            "safety": {
                "browser_opened": False,
                "network_contacted": False,
                "final_submit_clicked": False,
                "recruiter_outreach_sent": False,
                "runtime_settings_changed": False,
                "submission_authorized": False,
                "outreach_authorized": False,
            },
            "resumable": {
                "run_id": resumable_run.id,
                "task_id": resumable_task.id,
                "checkpoint_hash": envelope.get("checkpoint_hash"),
                "requeue_count": requeued.get("requeue_count"),
                "attempt_count": resumable_task.attempt_count,
                "max_attempts": resumable_task.max_attempts,
            },
            "drift": {
                "run_id": drift_run.id,
                "task_id": drift_task.id,
                "blocked": drift_blocked,
                "error": drift_error,
            },
            "assertions": assertions,
            "certification_metadata": {
                "dead_letter_verified": assertions["dead_letter_created"],
                "checkpoint_resume_verified": assertions["verified_checkpoint_requeue"],
                "checkpoint_drift_blocked": assertions["checkpoint_drift_blocked"],
                "submission_authorized": False,
                "outreach_authorized": False,
            },
        }
        report["report_sha256"] = _canonical_hash(report)
        if output_path is not None:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report
    finally:
        db.close()
        engine.dispose()


__all__ = ["DRILL_VERSION", "run_dead_letter_recovery_drill"]
