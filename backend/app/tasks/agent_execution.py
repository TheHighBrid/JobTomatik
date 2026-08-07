from __future__ import annotations

import logging

from celery.exceptions import Retry
from sqlalchemy.orm import selectinload

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.intelligence import AgentRun, AgentTask
from app.models.notification import Notification, NotificationType
from app.services.agent_execution import (
    HandlerResult,
    claim_task,
    execute_handler,
    execution_snapshot,
    persist_handler_result,
    queue_ready_tasks,
    refresh_run_status,
)

logger = logging.getLogger(__name__)


def _load_run(db, run_id: int, *, for_update: bool = False):
    query = (
        db.query(AgentRun)
        .options(selectinload(AgentRun.tasks))
        .filter(AgentRun.id == run_id)
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _mark_enqueue_failure(task_id: int, celery_task_id: str, error: Exception) -> None:
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).with_for_update().first()
        if not task:
            return
        execution = dict((task.task_output or {}).get("execution") or {})
        if execution.get("celery_task_id") != celery_task_id:
            return
        task.status = "pending"
        task.error = f"Task dispatch failed: {str(error)[:300]}"
        task.task_output = {
            **dict(task.task_output or {}),
            "execution": {
                **execution,
                "dispatch_failed": True,
                "dispatch_error": str(error)[:300],
            },
        }
        run = _load_run(db, task.run_id)
        if run:
            refresh_run_status(run)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not persist agent task enqueue failure")
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="app.tasks.agent_execution.dispatch_agent_run",
    queue="followup",
)
def dispatch_agent_run_task(self, run_id: int):
    db = SessionLocal()
    queued: list[tuple[int, str]] = []
    try:
        run = _load_run(db, run_id, for_update=True)
        if run is None:
            return {"error": "Agent run not found", "run_id": run_id}
        queued = queue_ready_tasks(run)
        snapshot = execution_snapshot(run)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("dispatch_agent_run_task failed for run %s", run_id)
        raise
    finally:
        db.close()

    dispatched = []
    for task_id, celery_task_id in queued:
        try:
            execute_agent_task.apply_async(
                args=[task_id],
                task_id=celery_task_id,
                queue="followup",
            )
            dispatched.append(
                {
                    "agent_task_id": task_id,
                    "celery_task_id": celery_task_id,
                }
            )
        except Exception as exc:
            _mark_enqueue_failure(task_id, celery_task_id, exc)

    return {
        "run_id": run_id,
        "dispatch_task_id": self.request.id,
        "dispatched": dispatched,
        "count": len(dispatched),
        "snapshot": snapshot,
    }


@celery_app.task(
    bind=True,
    name="app.tasks.agent_execution.execute_agent_task",
    queue="followup",
    max_retries=2,
)
def execute_agent_task(self, agent_task_id: int):
    db = SessionLocal()
    run_id = None
    try:
        task = (
            db.query(AgentTask)
            .filter(AgentTask.id == agent_task_id)
            .with_for_update()
            .first()
        )
        if task is None:
            return {"error": "Agent task not found", "agent_task_id": agent_task_id}
        run_id = task.run_id
        run = _load_run(db, run_id)
        if run is None:
            return {"error": "Agent run not found", "run_id": run_id}

        claimed, reason = claim_task(
            run,
            task,
            celery_task_id=self.request.id,
        )
        snapshot = execution_snapshot(run)
        db.commit()
        if not claimed:
            return {
                "agent_task_id": agent_task_id,
                "run_id": run_id,
                "claimed": False,
                "reason": reason,
                "snapshot": snapshot,
            }

        db.expire_all()
        run = _load_run(db, run_id)
        task = db.query(AgentTask).filter(AgentTask.id == agent_task_id).first()
        if run is None or task is None:
            return {"error": "Agent execution state disappeared", "run_id": run_id}

        result = execute_handler(db, run, task)
        persist_handler_result(run, task, result)
        if result.status in {"blocked", "failed"}:
            db.add(
                Notification(
                    user_id=run.user_id,
                    type=NotificationType.system,
                    title=f"Agent run #{run.id} needs attention",
                    message=result.error or f"{task.name} ended in {result.status}.",
                    data={
                        "agent_run_id": run.id,
                        "agent_task_id": task.id,
                        "agent_type": task.agent_type,
                        "status": result.status,
                    },
                )
            )
        db.commit()
        output = {
            "agent_task_id": agent_task_id,
            "run_id": run_id,
            "status": task.status,
            "task_output": task.task_output or {},
            "error": task.error,
        }
    except Retry:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("execute_agent_task failed for task %s", agent_task_id)

        retry_db = SessionLocal()
        try:
            task = (
                retry_db.query(AgentTask)
                .filter(AgentTask.id == agent_task_id)
                .with_for_update()
                .first()
            )
            if task is None:
                raise
            run_id = task.run_id
            run = _load_run(retry_db, run_id)
            can_retry = task.attempt_count < task.max_attempts
            execution = dict((task.task_output or {}).get("execution") or {})
            task.task_output = {
                **dict(task.task_output or {}),
                "execution": {
                    **execution,
                    "failure_class": "worker_exception",
                    "retryable": can_retry,
                    "failure_message": str(exc)[:500],
                },
            }
            task.error = str(exc)[:1000]
            if can_retry:
                task.status = "queued"
            else:
                persist_handler_result(
                    run,
                    task,
                    HandlerResult(
                        "failed",
                        {},
                        task.error,
                        retryable=False,
                        failure_class="attempt_limit_reached",
                    ),
                )
            refresh_run_status(run)
            attempt_count = task.attempt_count
            retry_db.commit()
        except Exception:
            retry_db.rollback()
            logger.exception("Could not persist agent task failure")
            raise
        finally:
            retry_db.close()

        if can_retry:
            raise self.retry(exc=exc, countdown=min(120, 20 * max(1, attempt_count)))
        output = {
            "agent_task_id": agent_task_id,
            "run_id": run_id,
            "status": "failed",
            "error": str(exc)[:1000],
        }
    finally:
        db.close()

    if run_id is not None:
        dispatch_agent_run_task.delay(run_id)
    return output
