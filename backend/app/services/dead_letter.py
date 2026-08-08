"""Durable dead-letter envelopes for bounded local agent execution.

Dead-letter state is stored inside the existing ``AgentTask.task_output`` JSON so the
queue works for every bounded task, including discovery tasks with no Application row.
The envelope is evidence and recovery control only: it never authorizes application
submission, recruiter outreach, or adapter-maturity changes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.models.intelligence import AgentRun, AgentTask
from app.models.notification import Notification, NotificationType
from app.services.agent_execution import (
    approval_is_satisfied,
    execution_control,
    plan_task_id,
    refresh_run_status,
)


DEAD_LETTER_KEY = "dead_letter"
DEAD_LETTER_VERSION = "bounded-dead-letter-v1"
MAX_DEAD_LETTER_REQUEUES = 2
DEPENDENCY_SKIP_ERRORS = {
    "Skipped because a dependency did not complete safely",
    "Dependency failed or blocked",
}


class DeadLetterError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utcnow()).replace(microsecond=0).isoformat()


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dependency_snapshot(run: AgentRun, task: AgentTask) -> list[dict[str, Any]]:
    by_plan_id = {plan_task_id(run, item): item for item in run.tasks}
    rows: list[dict[str, Any]] = []
    for dependency_id in sorted(str(value) for value in list(task.dependencies or [])):
        dependency = by_plan_id.get(dependency_id)
        if dependency is None:
            rows.append({
                "plan_task_id": dependency_id,
                "task_id": None,
                "status": "missing",
                "output_hash": None,
            })
            continue
        output = dict(dependency.task_output or {})
        rows.append({
            "plan_task_id": dependency_id,
            "task_id": dependency.id,
            "status": dependency.status,
            "output_hash": _canonical_hash(output),
        })
    return rows


def checkpoint_payload(run: AgentRun, task: AgentTask) -> dict[str, Any]:
    """Build the stable checkpoint that must still match before a manual requeue."""

    context = dict(run.run_context or {})
    control = execution_control(run)
    stable_context = {
        key: context.get(key)
        for key in (
            "application_id",
            "job_id",
            "pipeline",
            "search_params",
            "selector_requirements",
        )
        if key in context
    }
    return {
        "version": DEAD_LETTER_VERSION,
        "run_id": run.id,
        "user_id": run.user_id,
        "task_id": task.id,
        "plan_task_id": plan_task_id(run, task),
        "agent_type": task.agent_type,
        "task_input": dict(task.task_input or {}),
        "dependencies": _dependency_snapshot(run, task),
        "run_plan_hash": _canonical_hash(list(run.plan or [])),
        "stable_run_context": stable_context,
        "approval": {
            "state": control.get("approval_state"),
            "approved_by_user_id": control.get("approved_by_user_id"),
            "scope": control.get("scope"),
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    }


def checkpoint_hash(run: AgentRun, task: AgentTask) -> str:
    return _canonical_hash(checkpoint_payload(run, task))


def expected_requeue_acknowledgment(task: AgentTask, checkpoint: str) -> str:
    return f"REQUEUE DEAD LETTER {task.id} {checkpoint[:12]}"


def expected_resolve_acknowledgment(task: AgentTask, checkpoint: str) -> str:
    return f"RESOLVE DEAD LETTER {task.id} {checkpoint[:12]}"


def _envelope(task: AgentTask) -> dict[str, Any] | None:
    value = (task.task_output or {}).get(DEAD_LETTER_KEY)
    return dict(value) if isinstance(value, dict) else None


def route_task_to_dead_letter(
    db: Session,
    run: AgentRun,
    task: AgentTask,
    *,
    failure_class: str,
    error: str | None,
    source: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist an idempotent fail-closed dead-letter envelope for one task."""

    current = now or _utcnow()
    payload = checkpoint_payload(run, task)
    digest = _canonical_hash(payload)
    previous = _envelope(task) or {}
    if previous.get("status") == "open" and previous.get("checkpoint_hash") == digest:
        return previous

    history = list(previous.get("history") or [])[-8:]
    if previous:
        history.append({
            "status": previous.get("status"),
            "checkpoint_hash": previous.get("checkpoint_hash"),
            "opened_at": previous.get("opened_at"),
            "requeued_at": previous.get("requeued_at"),
            "resolved_at": previous.get("resolved_at"),
        })
    requeue_count = int(previous.get("requeue_count") or 0)
    envelope = {
        "version": DEAD_LETTER_VERSION,
        "status": "open",
        "failure_class": str(failure_class or "unknown")[:100],
        "failure_source": str(source or "unknown")[:100],
        "error": str(error or task.error or "bounded task failed")[:1000],
        "checkpoint_hash": digest,
        "checkpoint": payload,
        "opened_at": _iso(current),
        "automatic_retry_allowed": False,
        "requeue_count": requeue_count,
        "requeue_limit": MAX_DEAD_LETTER_REQUEUES,
        "expected_requeue_acknowledgment": expected_requeue_acknowledgment(task, digest),
        "expected_resolve_acknowledgment": expected_resolve_acknowledgment(task, digest),
        "recovery_path": f"/recovery?run={run.id}&task={task.id}",
        "submission_authorized": False,
        "outreach_authorized": False,
        "history": history,
    }
    task.status = "failed"
    task.error = envelope["error"]
    task.completed_at = task.completed_at or current
    task.task_output = {
        **dict(task.task_output or {}),
        DEAD_LETTER_KEY: envelope,
    }
    refresh_run_status(run)

    db.add(Notification(
        user_id=run.user_id,
        type=NotificationType.system,
        title=f"Dead-letter task requires review: {task.name}",
        message=(
            "Automatic retry stopped. Verify the retained checkpoint before any "
            "bounded requeue."
        ),
        data={
            "kind": "bounded_dead_letter",
            "agent_run_id": run.id,
            "agent_task_id": task.id,
            "agent_type": task.agent_type,
            "failure_class": envelope["failure_class"],
            "checkpoint_hash": digest,
            "recovery_path": envelope["recovery_path"],
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    ))
    return envelope


def _owned_task(db: Session, *, user_id: int, task_id: int) -> tuple[AgentRun, AgentTask]:
    task = (
        db.query(AgentTask)
        .join(AgentRun, AgentTask.run_id == AgentRun.id)
        .filter(AgentTask.id == task_id, AgentRun.user_id == user_id)
        .with_for_update()
        .first()
    )
    if task is None:
        raise DeadLetterError("Dead-letter task not found")
    run = (
        db.query(AgentRun)
        .options(selectinload(AgentRun.tasks))
        .filter(AgentRun.id == task.run_id, AgentRun.user_id == user_id)
        .with_for_update()
        .first()
    )
    if run is None:
        raise DeadLetterError("Agent run not found")
    task = next((item for item in run.tasks if item.id == task_id), None)
    if task is None:
        raise DeadLetterError("Dead-letter task disappeared")
    return run, task


def _reset_dependency_skips(run: AgentRun) -> list[int]:
    reset: list[int] = []
    for task in run.tasks:
        if task.status != "skipped" or task.error not in DEPENDENCY_SKIP_ERRORS:
            continue
        output = dict(task.task_output or {})
        if not output.get("dependency_failures") and not output.get("dependency_blockers"):
            continue
        task.status = "pending"
        task.error = None
        task.completed_at = None
        task.task_output = {
            **output,
            "dead_letter_dependency_reset": {
                "reset_at": _iso(),
                "reason": "upstream_dead_letter_requeued",
            },
        }
        reset.append(task.id)
    return reset


def requeue_dead_letter(
    db: Session,
    *,
    user_id: int,
    task_id: int,
    acknowledgment: str,
) -> dict[str, Any]:
    """Reopen exactly one failed bounded task after checkpoint verification."""

    run, task = _owned_task(db, user_id=user_id, task_id=task_id)
    envelope = _envelope(task)
    if not envelope or envelope.get("status") != "open":
        raise DeadLetterError("Task does not have an open dead-letter envelope")

    stored_hash = str(envelope.get("checkpoint_hash") or "")
    current_hash = checkpoint_hash(run, task)
    if not stored_hash or current_hash != stored_hash:
        raise DeadLetterError("Dead-letter checkpoint drift detected; requeue is blocked")

    expected = expected_requeue_acknowledgment(task, stored_hash)
    if acknowledgment.strip() != expected:
        raise DeadLetterError(f"Exact dead-letter acknowledgment required: {expected}")

    control = execution_control(run)
    if control.get("cancellation_requested"):
        raise DeadLetterError("Cancelled agent runs cannot be requeued")
    if control.get("paused"):
        raise DeadLetterError("Paused agent runs must be resumed before dead-letter requeue")
    if not approval_is_satisfied(run):
        raise DeadLetterError("Bounded-run approval is not currently satisfied")
    if control.get("submission_authorized") or control.get("outreach_authorized"):
        raise DeadLetterError("Dead-letter recovery cannot inherit consequential authorization")

    requeue_count = int(envelope.get("requeue_count") or 0)
    if requeue_count >= MAX_DEAD_LETTER_REQUEUES:
        raise DeadLetterError("Dead-letter requeue limit reached")

    now = _utcnow()
    updated = {
        **envelope,
        "status": "requeued",
        "requeued_at": _iso(now),
        "requeued_by_user_id": user_id,
        "requeue_count": requeue_count + 1,
        "automatic_retry_allowed": False,
    }
    task.task_output = {
        **dict(task.task_output or {}),
        DEAD_LETTER_KEY: updated,
    }
    task.status = "pending"
    task.error = None
    task.completed_at = None
    # Preserve historical attempt_count and permit exactly one additional bounded claim.
    task.max_attempts = max(int(task.max_attempts or 0), int(task.attempt_count or 0) + 1)
    reset_task_ids = _reset_dependency_skips(run)
    run.completed_at = None
    run.error = None
    refresh_run_status(run)
    return {
        "run_id": run.id,
        "task_id": task.id,
        "status": task.status,
        "checkpoint_hash": stored_hash,
        "requeue_count": updated["requeue_count"],
        "reset_dependency_task_ids": reset_task_ids,
        "dispatch_required": True,
        "submission_authorized": False,
        "outreach_authorized": False,
    }


def resolve_dead_letter(
    db: Session,
    *,
    user_id: int,
    task_id: int,
    acknowledgment: str,
    note: str,
) -> dict[str, Any]:
    """Acknowledge a dead letter without retrying or changing the failed task state."""

    run, task = _owned_task(db, user_id=user_id, task_id=task_id)
    envelope = _envelope(task)
    if not envelope or envelope.get("status") != "open":
        raise DeadLetterError("Task does not have an open dead-letter envelope")
    stored_hash = str(envelope.get("checkpoint_hash") or "")
    expected = expected_resolve_acknowledgment(task, stored_hash)
    if acknowledgment.strip() != expected:
        raise DeadLetterError(f"Exact dead-letter acknowledgment required: {expected}")
    task.task_output = {
        **dict(task.task_output or {}),
        DEAD_LETTER_KEY: {
            **envelope,
            "status": "resolved",
            "resolved_at": _iso(),
            "resolved_by_user_id": user_id,
            "resolution_note": note.strip()[:1000],
        },
    }
    return {
        "run_id": run.id,
        "task_id": task.id,
        "status": "resolved",
        "checkpoint_hash": stored_hash,
        "task_status": task.status,
        "dispatch_required": False,
        "submission_authorized": False,
        "outreach_authorized": False,
    }


def list_dead_letters(
    db: Session,
    *,
    user_id: int,
    status: str | None = "open",
    limit: int = 100,
) -> list[dict[str, Any]]:
    runs = (
        db.query(AgentRun)
        .options(selectinload(AgentRun.tasks))
        .filter(AgentRun.user_id == user_id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(max(1, min(int(limit), 500)))
        .all()
    )
    rows: list[dict[str, Any]] = []
    for run in runs:
        for task in run.tasks:
            envelope = _envelope(task)
            if not envelope:
                continue
            if status and status != "all" and envelope.get("status") != status:
                continue
            rows.append({
                "run_id": run.id,
                "run_status": run.status,
                "task_id": task.id,
                "plan_task_id": plan_task_id(run, task),
                "task_name": task.name,
                "agent_type": task.agent_type,
                "task_status": task.status,
                "attempt_count": task.attempt_count,
                "max_attempts": task.max_attempts,
                "dead_letter": envelope,
                "submission_authorized": False,
                "outreach_authorized": False,
            })
    rows.sort(
        key=lambda row: str((row["dead_letter"] or {}).get("opened_at") or ""),
        reverse=True,
    )
    return rows[: max(1, min(int(limit), 500))]


__all__ = [
    "DEAD_LETTER_KEY",
    "DEAD_LETTER_VERSION",
    "MAX_DEAD_LETTER_REQUEUES",
    "DeadLetterError",
    "checkpoint_hash",
    "checkpoint_payload",
    "expected_requeue_acknowledgment",
    "expected_resolve_acknowledgment",
    "list_dead_letters",
    "requeue_dead_letter",
    "resolve_dead_letter",
    "route_task_to_dead_letter",
]
