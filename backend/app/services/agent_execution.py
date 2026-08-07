from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine
from uuid import uuid4

from sqlalchemy.orm import Session, selectinload

from app.models.application import (
    Application,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.evaluation import OpportunityEvaluation
from app.models.intelligence import (
    AgentRun,
    AgentTask,
    CareerMemory,
    KnowledgeNode,
    RecruiterContact,
    SelectorStrategy,
)
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.user import User
from app.services.discovery_pipeline import persist_discovery_results
from app.services.discovery_search import search_jobs
from app.services.intelligence_foundation import derive_run_status, selector_health_score
from app.services.material_generation import generate_application_material


HANDLER_VERSION = "bounded-agent-execution-v1"
EXECUTION_SCOPE = "bounded_local_execution"
CONTROL_KEY = "execution_control"
LEASE_SECONDS = 15 * 60
SELECTOR_HEALTH_THRESHOLD = 0.55

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_NOT_REQUIRED = "not_required"
APPROVAL_REVOKED = "revoked"

TASK_TERMINAL = {"completed", "failed", "skipped"}
RUN_TERMINAL = {"completed", "failed", "cancelled"}
SUPPORTED_AGENT_TYPES = {
    "discovery",
    "deduplication",
    "company_research",
    "evaluation",
    "tailoring",
    "application",
    "recruiter_crm",
    "interview_intelligence",
    "interview_coach",
    "offer_intelligence",
    "memory",
}


@dataclass
class HandlerResult:
    status: str
    output: dict[str, Any]
    error: str | None = None
    retryable: bool = False
    failure_class: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def execution_control(run: AgentRun) -> dict[str, Any]:
    context = dict(run.run_context or {})
    control = dict(context.get(CONTROL_KEY) or {})
    if not control:
        control = {
            "approval_state": APPROVAL_PENDING if run.requires_approval else APPROVAL_NOT_REQUIRED,
            "scope": EXECUTION_SCOPE,
            "paused": False,
            "cancellation_requested": False,
            "submission_authorized": False,
            "outreach_authorized": False,
            "created_at": iso_now(),
        }
        context[CONTROL_KEY] = control
        run.run_context = context
    return control


def set_execution_control(run: AgentRun, control: dict[str, Any]) -> None:
    context = dict(run.run_context or {})
    context[CONTROL_KEY] = control
    run.run_context = context


def approval_is_satisfied(run: AgentRun) -> bool:
    state = execution_control(run).get("approval_state")
    return state in {APPROVAL_APPROVED, APPROVAL_NOT_REQUIRED}


def approve_run(run: AgentRun, *, user_id: int, note: str | None = None) -> dict[str, Any]:
    if run.status in RUN_TERMINAL:
        raise ValueError("Terminal agent runs cannot be approved")
    control = execution_control(run)
    control.update(
        {
            "approval_state": APPROVAL_APPROVED,
            "approved_at": iso_now(),
            "approved_by_user_id": user_id,
            "approval_note": (note or "").strip() or None,
            "scope": EXECUTION_SCOPE,
            "submission_authorized": False,
            "outreach_authorized": False,
            "paused": False,
        }
    )
    set_execution_control(run, control)
    return control


def reject_run(run: AgentRun, *, user_id: int, reason: str) -> dict[str, Any]:
    if run.status in RUN_TERMINAL:
        raise ValueError("Terminal agent runs cannot be rejected")
    control = execution_control(run)
    control.update(
        {
            "approval_state": APPROVAL_REJECTED,
            "rejected_at": iso_now(),
            "rejected_by_user_id": user_id,
            "rejection_reason": reason.strip(),
            "paused": True,
        }
    )
    set_execution_control(run, control)
    run.status = "blocked"
    run.error = reason.strip()
    return control


def pause_run(run: AgentRun, *, reason: str, user_id: int) -> dict[str, Any]:
    if run.status in RUN_TERMINAL:
        raise ValueError("Terminal agent runs cannot be paused")
    control = execution_control(run)
    control.update(
        {
            "paused": True,
            "paused_at": iso_now(),
            "paused_by_user_id": user_id,
            "pause_reason": reason.strip(),
        }
    )
    set_execution_control(run, control)
    run.status = "blocked"
    return control


def resume_run(run: AgentRun, *, user_id: int) -> dict[str, Any]:
    if run.status in RUN_TERMINAL:
        raise ValueError("Terminal agent runs cannot be resumed")
    control = execution_control(run)
    if control.get("approval_state") in {APPROVAL_REJECTED, APPROVAL_REVOKED}:
        raise ValueError("Rejected or revoked runs require a new approval")
    control.update(
        {
            "paused": False,
            "resumed_at": iso_now(),
            "resumed_by_user_id": user_id,
            "pause_reason": None,
        }
    )
    set_execution_control(run, control)
    refresh_run_status(run)
    return control


def cancel_run(run: AgentRun, *, user_id: int, reason: str) -> dict[str, Any]:
    if run.status in RUN_TERMINAL:
        return execution_control(run)
    control = execution_control(run)
    control.update(
        {
            "cancellation_requested": True,
            "cancelled_at": iso_now(),
            "cancelled_by_user_id": user_id,
            "cancellation_reason": reason.strip(),
            "paused": True,
        }
    )
    set_execution_control(run, control)
    for task in run.tasks:
        if task.status in {"pending", "queued", "blocked"}:
            task.status = "skipped"
            task.error = "Run cancelled before task execution"
            task.completed_at = utcnow()
            task.task_output = {
                **dict(task.task_output or {}),
                "execution": {
                    **dict((task.task_output or {}).get("execution") or {}),
                    "cancelled": True,
                    "cancellation_reason": reason.strip(),
                },
            }
    run.status = "cancelled"
    run.error = reason.strip()
    run.completed_at = utcnow()
    return control


def plan_task_id(run: AgentRun, task: AgentTask) -> str:
    task_input = dict(task.task_input or {})
    if task_input.get("plan_task_id"):
        return str(task_input["plan_task_id"])
    plan = list(run.plan or [])
    if 0 <= int(task.sequence or 0) < len(plan):
        candidate = plan[int(task.sequence or 0)]
        if isinstance(candidate, dict) and candidate.get("id"):
            return str(candidate["id"])
    return f"task-{task.id}"


def _task_map(run: AgentRun) -> dict[str, AgentTask]:
    return {plan_task_id(run, task): task for task in run.tasks}


def dependency_state(run: AgentRun, task: AgentTask) -> tuple[bool, list[dict[str, Any]]]:
    task_map = _task_map(run)
    blockers: list[dict[str, Any]] = []
    for dependency_id in list(task.dependencies or []):
        dependency = task_map.get(str(dependency_id))
        if dependency is None:
            blockers.append(
                {
                    "dependency": str(dependency_id),
                    "status": "missing",
                    "reason": "dependency_not_found",
                }
            )
            continue
        if dependency.status not in {"completed", "skipped"}:
            blockers.append(
                {
                    "dependency": str(dependency_id),
                    "task_id": dependency.id,
                    "status": dependency.status,
                    "reason": (
                        "dependency_terminal_failure"
                        if dependency.status in {"failed", "blocked"}
                        else "dependency_not_complete"
                    ),
                }
            )
    return not blockers, blockers


def refresh_run_status(run: AgentRun) -> str:
    control = execution_control(run)
    if control.get("cancellation_requested"):
        run.status = "cancelled"
        run.completed_at = run.completed_at or utcnow()
        return run.status
    if control.get("paused"):
        run.status = "blocked"
        return run.status
    statuses = [task.status for task in run.tasks]
    normalized = ["pending" if status == "queued" else status for status in statuses]
    run.status = derive_run_status(normalized)
    if run.status == "running":
        run.started_at = run.started_at or utcnow()
    if run.status in {"completed", "failed"}:
        run.completed_at = run.completed_at or utcnow()
        run.result = {
            **dict(run.result or {}),
            "execution_scope": EXECUTION_SCOPE,
            "handler_version": HANDLER_VERSION,
            "tasks": [
                {
                    "id": task.id,
                    "plan_task_id": plan_task_id(run, task),
                    "agent_type": task.agent_type,
                    "status": task.status,
                    "attempt_count": task.attempt_count,
                    "task_output": task.task_output or {},
                    "error": task.error,
                }
                for task in run.tasks
            ],
        }
    return run.status


def settle_dependency_failures(run: AgentRun) -> list[int]:
    changed: list[int] = []
    task_map = _task_map(run)
    for task in run.tasks:
        if task.status not in {"pending", "queued"}:
            continue
        failed_dependencies = []
        for dependency_id in list(task.dependencies or []):
            dependency = task_map.get(str(dependency_id))
            if dependency and dependency.status in {"failed", "blocked"}:
                failed_dependencies.append(
                    {
                        "dependency": str(dependency_id),
                        "task_id": dependency.id,
                        "status": dependency.status,
                    }
                )
        if failed_dependencies:
            task.status = "skipped"
            task.completed_at = utcnow()
            task.error = "Skipped because a dependency did not complete safely"
            task.task_output = {
                **dict(task.task_output or {}),
                "dependency_failures": failed_dependencies,
            }
            changed.append(task.id)
    return changed


def ready_tasks(run: AgentRun) -> list[AgentTask]:
    if not approval_is_satisfied(run):
        return []
    control = execution_control(run)
    if control.get("paused") or control.get("cancellation_requested"):
        return []
    ready = []
    for task in sorted(run.tasks, key=lambda item: (item.sequence, item.id)):
        if task.status != "pending":
            continue
        satisfied, _ = dependency_state(run, task)
        if satisfied:
            ready.append(task)
    return ready


def execution_snapshot(run: AgentRun) -> dict[str, Any]:
    control = execution_control(run)
    ready = ready_tasks(run)
    return {
        "run_id": run.id,
        "status": run.status,
        "objective": run.objective,
        "risk_level": run.risk_level,
        "requires_approval": run.requires_approval,
        "approval_state": control.get("approval_state"),
        "execution_scope": control.get("scope", EXECUTION_SCOPE),
        "paused": bool(control.get("paused")),
        "cancellation_requested": bool(control.get("cancellation_requested")),
        "submission_authorized": False,
        "outreach_authorized": False,
        "ready_task_ids": [task.id for task in ready],
        "task_counts": {
            status: sum(1 for task in run.tasks if task.status == status)
            for status in sorted({task.status for task in run.tasks})
        },
        "tasks": [
            {
                "id": task.id,
                "plan_task_id": plan_task_id(run, task),
                "sequence": task.sequence,
                "name": task.name,
                "agent_type": task.agent_type,
                "status": task.status,
                "dependencies": list(task.dependencies or []),
                "attempt_count": task.attempt_count,
                "max_attempts": task.max_attempts,
                "task_output": task.task_output or {},
                "error": task.error,
            }
            for task in sorted(run.tasks, key=lambda item: (item.sequence, item.id))
        ],
        "control": control,
    }


def queue_ready_tasks(run: AgentRun) -> list[tuple[int, str]]:
    settle_dependency_failures(run)
    queued: list[tuple[int, str]] = []
    for task in ready_tasks(run):
        celery_task_id = uuid4().hex
        task.status = "queued"
        task.task_output = {
            **dict(task.task_output or {}),
            "execution": {
                **dict((task.task_output or {}).get("execution") or {}),
                "celery_task_id": celery_task_id,
                "queued_at": iso_now(),
                "handler_version": HANDLER_VERSION,
            },
        }
        queued.append((task.id, celery_task_id))
    if queued:
        run.status = "running"
        run.started_at = run.started_at or utcnow()
    else:
        refresh_run_status(run)
    return queued


def claim_task(
    run: AgentRun,
    task: AgentTask,
    *,
    celery_task_id: str | None,
) -> tuple[bool, str]:
    control = execution_control(run)
    if control.get("cancellation_requested"):
        if task.status not in TASK_TERMINAL:
            task.status = "skipped"
            task.completed_at = utcnow()
            task.error = "Run cancellation was requested"
        return False, "run_cancelled"
    if control.get("paused"):
        return False, "run_paused"
    if not approval_is_satisfied(run):
        return False, "approval_required"
    if task.status in TASK_TERMINAL:
        return False, "task_terminal"
    if task.agent_type not in SUPPORTED_AGENT_TYPES:
        task.status = "blocked"
        task.error = f"Unsupported bounded agent type: {task.agent_type}"
        task.completed_at = utcnow()
        refresh_run_status(run)
        return False, "unsupported_agent_type"

    satisfied, blockers = dependency_state(run, task)
    if not satisfied:
        terminal = any(item["reason"] == "dependency_terminal_failure" for item in blockers)
        if terminal:
            task.status = "skipped"
            task.completed_at = utcnow()
            task.error = "Dependency failed or blocked"
            task.task_output = {
                **dict(task.task_output or {}),
                "dependency_blockers": blockers,
            }
            refresh_run_status(run)
        return False, "dependencies_not_ready"

    execution = dict((task.task_output or {}).get("execution") or {})
    lease_expires_at = _parse_datetime(execution.get("lease_expires_at"))
    if task.status == "running" and lease_expires_at and lease_expires_at > utcnow():
        return False, "task_already_claimed"
    if task.attempt_count >= task.max_attempts:
        task.status = "failed"
        task.error = "Maximum bounded execution attempts exceeded"
        task.completed_at = utcnow()
        refresh_run_status(run)
        return False, "attempt_limit_reached"

    now = utcnow()
    task.status = "running"
    task.attempt_count += 1
    task.started_at = task.started_at or now
    task.error = None
    task.task_output = {
        **dict(task.task_output or {}),
        "execution": {
            **execution,
            "celery_task_id": celery_task_id or execution.get("celery_task_id"),
            "claimed_at": now.isoformat(),
            "lease_expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
            "handler_version": HANDLER_VERSION,
            "attempt": task.attempt_count,
        },
    }
    run.status = "running"
    run.started_at = run.started_at or now
    return True, "claimed"


def _resolve_application_and_job(
    db: Session,
    run: AgentRun,
    task: AgentTask,
) -> tuple[User, Application | None, Job | None]:
    context = dict(run.run_context or {})
    task_input = dict(task.task_input or {})
    application_id = task_input.get("application_id") or context.get("application_id")
    job_id = task_input.get("job_id") or context.get("job_id")

    user = db.query(User).filter(User.id == run.user_id).first()
    if user is None:
        raise RuntimeError("Agent run user no longer exists")

    application = None
    if application_id:
        application = (
            db.query(Application)
            .filter(
                Application.id == int(application_id),
                Application.user_id == run.user_id,
            )
            .first()
        )
        if application is None:
            raise ValueError("Application not found for this agent run")
        job_id = application.job_id

    job = None
    if job_id:
        job = db.query(Job).filter(Job.id == int(job_id)).first()
        if job is None:
            raise ValueError("Job not found for this agent run")
    return user, application, job


def _previous_task_output(run: AgentRun, agent_type: str) -> dict[str, Any]:
    candidates = [
        task
        for task in run.tasks
        if task.agent_type == agent_type and task.status == "completed"
    ]
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item.sequence, item.id), reverse=True)
    return dict(candidates[0].task_output or {})


def _bounded_job_snapshot(job: Job) -> dict[str, Any]:
    raw = dict(job.raw_data or {})
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "source": str(job.source.value if hasattr(job.source, "value") else job.source),
        "skills": list(job.skills or [])[:20],
        "seniority": job.seniority,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "official_public_ats": bool(raw.get("official_public_ats")),
        "ats_identifier": raw.get("ats_identifier"),
        "provider_api_url": raw.get("provider_api_url"),
    }


def _handle_discovery(
    db: Session,
    run: AgentRun,
    task: AgentTask,
    user: User,
) -> HandlerResult:
    context = dict(run.run_context or {})
    task_input = dict(task.task_input or {})
    search_params = dict(task_input.get("search_params") or context.get("search_params") or {})
    if not search_params:
        return HandlerResult(
            "blocked",
            {"blocker": "search_params_required"},
            "Discovery requires explicit search_params",
        )
    keywords = str(search_params.get("keywords") or "").strip()
    if not keywords:
        return HandlerResult(
            "blocked",
            {"blocker": "keywords_required"},
            "Discovery requires explicit keywords",
        )
    raw_jobs = _run_async(search_jobs(**search_params))
    stats = persist_discovery_results(
        db,
        user,
        raw_jobs,
        keywords=keywords,
        search_params=search_params,
        track_agent_run=False,
    )
    return HandlerResult("completed", stats)


def _handle_deduplication(run: AgentRun) -> HandlerResult:
    discovery = _previous_task_output(run, "discovery")
    if not discovery:
        return HandlerResult(
            "blocked",
            {"blocker": "discovery_output_missing"},
            "Discovery output is required before deduplication",
        )
    return HandlerResult(
        "completed",
        {
            "duplicates": int(discovery.get("duplicates") or 0),
            "saved": int(discovery.get("saved") or 0),
            "blocked": int(discovery.get("blocked") or 0),
            "source": "discovery_pipeline",
        },
    )


def _handle_company_research(
    db: Session,
    run: AgentRun,
    job: Job | None,
) -> HandlerResult:
    if job is None:
        return HandlerResult(
            "blocked",
            {"blocker": "job_context_required"},
            "Company research requires a user-owned job or application context",
        )
    company_key = re.sub(r"[^a-z0-9]+", "-", (job.company or "").lower()).strip("-")
    nodes = (
        db.query(KnowledgeNode)
        .filter(
            KnowledgeNode.user_id == run.user_id,
            KnowledgeNode.external_key.in_([f"company:{company_key}", f"job:{job.id}"]),
        )
        .all()
    )
    return HandlerResult(
        "completed",
        {
            "job": _bounded_job_snapshot(job),
            "knowledge_nodes": [
                {
                    "id": node.id,
                    "node_type": node.node_type,
                    "label": node.label,
                    "confidence": node.confidence,
                    "payload": node.payload or {},
                    "source_url": node.source_url,
                }
                for node in nodes
            ],
            "external_research_performed": False,
        },
    )


def _handle_evaluation(
    db: Session,
    run: AgentRun,
    job: Job | None,
) -> HandlerResult:
    if job is None:
        discovery = _previous_task_output(run, "discovery")
        if discovery:
            return HandlerResult(
                "completed",
                {
                    "source": "discovery_pipeline",
                    "evaluations_created": int(discovery.get("evaluations_created") or 0),
                    "saved": int(discovery.get("saved") or 0),
                    "blocked": int(discovery.get("blocked") or 0),
                },
            )
        return HandlerResult(
            "blocked",
            {"blocker": "job_or_discovery_context_required"},
            "Evaluation requires a job context or completed discovery output",
        )

    evaluation = (
        db.query(OpportunityEvaluation)
        .filter(
            OpportunityEvaluation.user_id == run.user_id,
            OpportunityEvaluation.job_id == job.id,
        )
        .order_by(OpportunityEvaluation.created_at.desc())
        .first()
    )
    if evaluation is None:
        return HandlerResult(
            "blocked",
            {"blocker": "opportunity_evaluation_missing", "job_id": job.id},
            "No source-backed opportunity evaluation exists for this job",
        )
    return HandlerResult(
        "completed",
        {
            "evaluation_id": evaluation.id,
            "job_id": job.id,
            "recommendation": evaluation.recommendation,
            "weighted_score": evaluation.weighted_score,
            "legitimacy_status": evaluation.legitimacy_status,
            "hard_blockers": list(evaluation.hard_blockers or []),
            "dimension_scores": evaluation.dimension_scores or {},
        },
    )


def _handle_tailoring(
    db: Session,
    application: Application | None,
    user: User,
    job: Job | None,
) -> HandlerResult:
    if application is None or job is None:
        return HandlerResult(
            "blocked",
            {"blocker": "application_context_required"},
            "Verified material generation requires a user-owned application",
        )
    cover = generate_application_material(
        db,
        application,
        user,
        job,
        material_type="cover_letter",
        rebuild_evidence=True,
    )
    resume = generate_application_material(
        db,
        application,
        user,
        job,
        material_type="resume_summary",
        rebuild_evidence=False,
    )
    materials = [cover, resume]
    warnings = sorted(
        {
            warning
            for material in materials
            for warning in list(material.warnings or [])
        }
    )
    status = "completed" if all(material.status == "verified" for material in materials) else "blocked"
    return HandlerResult(
        status,
        {
            "application_id": application.id,
            "materials": [
                {
                    "id": material.id,
                    "material_type": material.material_type,
                    "version": material.version,
                    "status": material.status,
                    "warning_count": len(material.warnings or []),
                }
                for material in materials
            ],
            "warnings": warnings,
        },
        None if status == "completed" else "Generated materials require evidence review",
    )


def selector_readiness(
    db: Session,
    *,
    user_id: int,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    checks = []
    ready = True
    for requirement in requirements:
        platform = str(requirement.get("platform") or "").strip().lower()
        page_signature = str(requirement.get("page_signature") or "").strip()
        intent = str(requirement.get("intent") or "").strip()
        threshold = float(requirement.get("min_health") or SELECTOR_HEALTH_THRESHOLD)
        candidates = (
            db.query(SelectorStrategy)
            .filter(
                SelectorStrategy.user_id == user_id,
                SelectorStrategy.platform == platform,
                SelectorStrategy.page_signature == page_signature,
                SelectorStrategy.intent == intent,
                SelectorStrategy.is_disabled.is_(False),
            )
            .all()
        )
        best = None
        if candidates:
            best = max(
                candidates,
                key=lambda strategy: selector_health_score(
                    confidence=strategy.confidence,
                    success_count=strategy.success_count,
                    failure_count=strategy.failure_count,
                ),
            )
        health = (
            selector_health_score(
                confidence=best.confidence,
                success_count=best.success_count,
                failure_count=best.failure_count,
            )
            if best
            else 0.0
        )
        passed = bool(best and health >= threshold)
        ready = ready and passed
        checks.append(
            {
                "platform": platform,
                "page_signature": page_signature,
                "intent": intent,
                "threshold": threshold,
                "strategy_id": best.id if best else None,
                "selector": best.selector if best else None,
                "health_score": health,
                "passed": passed,
                "reason": (
                    None
                    if passed
                    else "selector_health_below_threshold"
                    if best
                    else "selector_strategy_missing"
                ),
            }
        )
    return {"ready": ready, "checks": checks}


def _handle_application_preflight(
    db: Session,
    run: AgentRun,
    application: Application | None,
    job: Job | None,
) -> HandlerResult:
    if application is None or job is None:
        return HandlerResult(
            "blocked",
            {"blocker": "application_context_required"},
            "Application preparation requires a user-owned application",
        )

    open_reviews = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .all()
    )
    latest_materials = {}
    for material_type in ("cover_letter", "resume_summary"):
        latest_materials[material_type] = (
            db.query(ApplicationMaterial)
            .filter(
                ApplicationMaterial.application_id == application.id,
                ApplicationMaterial.material_type == material_type,
            )
            .order_by(ApplicationMaterial.version.desc())
            .first()
        )

    blockers = []
    if open_reviews:
        blockers.append({"code": "manual_review_open", "review_ids": [review.id for review in open_reviews]})
    if not application.application_target_url:
        blockers.append({"code": "application_target_missing"})
    for material_type, material in latest_materials.items():
        if material is None:
            blockers.append({"code": f"{material_type}_missing"})
        elif material.status != "verified":
            blockers.append(
                {
                    "code": f"{material_type}_not_verified",
                    "material_id": material.id,
                    "status": material.status,
                }
            )

    context = dict(run.run_context or {})
    selector_requirements = [
        item
        for item in list(context.get("selector_requirements") or [])
        if isinstance(item, dict)
    ]
    selector_status = selector_readiness(
        db,
        user_id=run.user_id,
        requirements=selector_requirements,
    )
    if selector_requirements and not selector_status["ready"]:
        blockers.append({"code": "selector_readiness_failed", "checks": selector_status["checks"]})

    output = {
        "application_id": application.id,
        "job": _bounded_job_snapshot(job),
        "automation_state": application.automation_state,
        "application_target_status": application.application_target_status,
        "application_target_url_present": bool(application.application_target_url),
        "open_manual_reviews": len(open_reviews),
        "materials": {
            material_type: (
                {"id": material.id, "version": material.version, "status": material.status}
                if material
                else None
            )
            for material_type, material in latest_materials.items()
        },
        "selector_readiness": selector_status,
        "blockers": blockers,
        "ready_for_separate_submission_preflight": not blockers,
        "submission_attempted": False,
        "submission_authorized": False,
    }
    if blockers:
        return HandlerResult(
            "blocked",
            output,
            "Application remains blocked before separate submission preflight",
        )
    return HandlerResult("completed", output)


def _handle_recruiter_crm(
    db: Session,
    run: AgentRun,
    job: Job | None,
) -> HandlerResult:
    query = db.query(RecruiterContact).filter(RecruiterContact.user_id == run.user_id)
    if job is not None:
        query = query.filter(RecruiterContact.company.ilike(f"%{job.company}%"))
    contacts = (
        query.order_by(
            RecruiterContact.next_followup_at.asc(),
            RecruiterContact.updated_at.desc(),
        )
        .limit(10)
        .all()
    )
    return HandlerResult(
        "completed",
        {
            "contacts": [
                {
                    "id": contact.id,
                    "full_name": contact.full_name,
                    "company": contact.company,
                    "relationship_stage": contact.relationship_stage,
                    "relationship_score": contact.relationship_score,
                    "next_followup_at": contact.next_followup_at.isoformat() if contact.next_followup_at else None,
                }
                for contact in contacts
            ],
            "messages_sent": 0,
            "outreach_authorized": False,
        },
    )


def _job_tokens(job: Job | None) -> set[str]:
    if job is None:
        return set()
    text = " ".join(
        [
            job.title or "",
            job.company or "",
            job.description or "",
            job.requirements or "",
            " ".join(job.skills or []),
        ]
    )
    return {
        token.casefold()
        for token in re.findall(r"[a-z0-9][a-z0-9+.#/-]{2,}", text, re.I)
    }


def _handle_interview_intelligence(
    db: Session,
    run: AgentRun,
    job: Job | None,
) -> HandlerResult:
    units = (
        db.query(EvidenceUnit)
        .filter(EvidenceUnit.user_id == run.user_id, EvidenceUnit.is_active.is_(True))
        .all()
    )
    tokens = _job_tokens(job)
    ranked = []
    for unit in units:
        unit_tokens = {
            token.casefold()
            for token in re.findall(
                r"[a-z0-9][a-z0-9+.#/-]{2,}",
                " ".join(filter(None, [unit.label, unit.statement, unit.organization, unit.role])),
                re.I,
            )
        }
        overlap = len(tokens & unit_tokens)
        score = overlap * 2.0 + float(unit.confidence or 0.0)
        ranked.append((score, unit))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    selected = [unit for score, unit in ranked if score > 0][:8]
    if not selected:
        return HandlerResult(
            "blocked",
            {"blocker": "interview_evidence_missing"},
            "No active evidence units matched the role context",
        )
    return HandlerResult(
        "completed",
        {
            "job_id": job.id if job else None,
            "evidence_units": [
                {
                    "id": unit.id,
                    "kind": unit.kind,
                    "label": unit.label,
                    "statement": unit.statement,
                    "source_hash": unit.source_hash,
                    "verification_status": unit.verification_status,
                }
                for unit in selected
            ],
        },
    )


def _handle_interview_coach(
    run: AgentRun,
    job: Job | None,
) -> HandlerResult:
    evidence = _previous_task_output(run, "interview_intelligence")
    evidence_units = list(evidence.get("evidence_units") or [])
    if not evidence_units:
        return HandlerResult(
            "blocked",
            {"blocker": "interview_intelligence_missing"},
            "Interview coaching requires evidence-backed story candidates",
        )
    skills = list(job.skills or [])[:5] if job else []
    questions = [
        {
            "question": f"Describe a verified example that demonstrates {skill}.",
            "evidence_unit_ids": [item["id"] for item in evidence_units[:3]],
        }
        for skill in skills
    ]
    if not questions:
        questions = [
            {
                "question": "Describe a verified example relevant to this role.",
                "evidence_unit_ids": [item["id"] for item in evidence_units[:3]],
            }
        ]
    return HandlerResult(
        "completed",
        {
            "questions": questions,
            "answer_generation_performed": False,
            "truthful_evidence_required": True,
        },
    )


def _handle_offer_intelligence(
    application: Application | None,
    job: Job | None,
) -> HandlerResult:
    if application is None or job is None:
        return HandlerResult(
            "blocked",
            {"blocker": "application_context_required"},
            "Offer analysis requires an application context",
        )
    if not application.salary_offered:
        return HandlerResult(
            "blocked",
            {"blocker": "offer_terms_missing", "application_id": application.id},
            "No salary offer has been recorded",
        )
    return HandlerResult(
        "completed",
        {
            "application_id": application.id,
            "job_id": job.id,
            "salary_offered": application.salary_offered,
            "salary_currency": job.salary_currency,
            "salary_range": {"minimum": job.salary_min, "maximum": job.salary_max},
            "negotiation_sent": False,
            "acceptance_authorized": False,
        },
    )


def _handle_memory(
    db: Session,
    run: AgentRun,
) -> HandlerResult:
    context = dict(run.run_context or {})
    outcome = context.get("verified_outcome")
    persist = bool(context.get("persist_verified_outcome"))
    if not persist or not isinstance(outcome, dict):
        return HandlerResult(
            "completed",
            {"persisted": False, "reason": "no_explicit_verified_outcome"},
        )
    content = str(outcome.get("content") or "").strip()
    source_ref = str(outcome.get("source_ref") or "").strip()
    if not content or not source_ref:
        return HandlerResult(
            "blocked",
            {"blocker": "verified_outcome_source_required"},
            "Verified outcomes require exact content and source_ref",
        )
    memory = CareerMemory(
        user_id=run.user_id,
        kind=str(outcome.get("kind") or "outcome")[:50],
        key=str(outcome.get("key") or f"agent-run-{run.id}")[:255],
        content=content,
        confidence=max(0.0, min(float(outcome.get("confidence") or 1.0), 1.0)),
        source="agent_run_verified_outcome",
        source_ref=source_ref[:1000],
        memory_metadata={
            "agent_run_id": run.id,
            "verified_by_user": True,
            "execution_scope": EXECUTION_SCOPE,
        },
    )
    db.add(memory)
    db.flush()
    return HandlerResult(
        "completed",
        {"persisted": True, "memory_id": memory.id, "source_ref": source_ref},
    )


def execute_handler(
    db: Session,
    run: AgentRun,
    task: AgentTask,
) -> HandlerResult:
    user, application, job = _resolve_application_and_job(db, run, task)
    if task.agent_type == "discovery":
        return _handle_discovery(db, run, task, user)
    if task.agent_type == "deduplication":
        return _handle_deduplication(run)
    if task.agent_type == "company_research":
        return _handle_company_research(db, run, job)
    if task.agent_type == "evaluation":
        return _handle_evaluation(db, run, job)
    if task.agent_type == "tailoring":
        return _handle_tailoring(db, application, user, job)
    if task.agent_type == "application":
        return _handle_application_preflight(db, run, application, job)
    if task.agent_type == "recruiter_crm":
        return _handle_recruiter_crm(db, run, job)
    if task.agent_type == "interview_intelligence":
        return _handle_interview_intelligence(db, run, job)
    if task.agent_type == "interview_coach":
        return _handle_interview_coach(run, job)
    if task.agent_type == "offer_intelligence":
        return _handle_offer_intelligence(application, job)
    if task.agent_type == "memory":
        return _handle_memory(db, run)
    return HandlerResult(
        "blocked",
        {"blocker": "unsupported_agent_type", "agent_type": task.agent_type},
        f"Unsupported bounded agent type: {task.agent_type}",
    )


def persist_handler_result(
    run: AgentRun,
    task: AgentTask,
    result: HandlerResult,
) -> None:
    now = utcnow()
    execution = dict((task.task_output or {}).get("execution") or {})
    task.task_output = {
        **dict(task.task_output or {}),
        **dict(result.output or {}),
        "execution": {
            **execution,
            "finished_at": now.isoformat(),
            "handler_version": HANDLER_VERSION,
            "failure_class": result.failure_class,
            "retryable": result.retryable,
        },
    }
    task.error = result.error
    task.status = result.status
    if result.status in TASK_TERMINAL | {"blocked"}:
        task.completed_at = now
    refresh_run_status(run)


def load_owned_run(
    db: Session,
    *,
    run_id: int,
    user_id: int,
    for_update: bool = False,
) -> AgentRun | None:
    query = (
        db.query(AgentRun)
        .options(selectinload(AgentRun.tasks))
        .filter(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )
    if for_update:
        query = query.with_for_update()
    return query.first()
