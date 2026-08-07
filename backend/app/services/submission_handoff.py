"""Tamper-evident bridge from bounded execution to supervised preflight.

A handoff dossier is not a submission approval. It records a hash-only snapshot of
one completed bounded AgentRun, its application-readiness task, and the current
exact submission payload. Creation and review never issue an approval, reserve an
attempt, publish a worker task, open a browser, or authorize outreach/submission.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationEvent
from app.models.intelligence import AgentRun, AgentTask
from app.models.job import Job
from app.models.material import ApplicationMaterial
from app.models.user import User
from app.services.agent_execution import EXECUTION_SCOPE, execution_control, plan_task_id
from app.services.application_integrity import submission_is_closed
from app.services.supervised_submission import (
    build_submission_snapshot,
    build_supervised_preflight,
)


HANDOFF_VERSION = "bounded-submission-handoff-v1"
HANDOFF_KEY = "submission_handoff"


class SubmissionHandoffError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def create_acknowledgment(run_id: int) -> str:
    return f"CREATE SUBMISSION HANDOFF {run_id}"


def review_acknowledgment(run_id: int) -> str:
    return f"REVIEW SUBMISSION HANDOFF {run_id}"


def _application_task(run: AgentRun) -> AgentTask | None:
    tasks = [task for task in run.tasks if task.agent_type == "application"]
    if not tasks:
        return None
    tasks.sort(key=lambda task: (task.sequence, task.id), reverse=True)
    return tasks[0]


def _resolve_records(
    db: Session,
    run: AgentRun,
) -> tuple[User | None, Application | None, Job | None, AgentTask | None]:
    task = _application_task(run)
    output = dict(task.task_output or {}) if task else {}
    context = dict(run.run_context or {})
    application_id = context.get("application_id") or output.get("application_id")

    user = db.query(User).filter(User.id == run.user_id).first()
    application = None
    job = None
    if application_id:
        application = (
            db.query(Application)
            .filter(
                Application.id == int(application_id),
                Application.user_id == run.user_id,
            )
            .first()
        )
        if application:
            job = db.query(Job).filter(Job.id == application.job_id).first()
    return user, application, job, task


def _latest_materials(db: Session, application_id: int) -> dict[str, ApplicationMaterial | None]:
    result: dict[str, ApplicationMaterial | None] = {}
    for material_type in ("cover_letter", "resume_summary"):
        result[material_type] = (
            db.query(ApplicationMaterial)
            .filter(
                ApplicationMaterial.application_id == application_id,
                ApplicationMaterial.material_type == material_type,
            )
            .order_by(ApplicationMaterial.version.desc(), ApplicationMaterial.id.desc())
            .first()
        )
    return result


def _task_ledger(run: AgentRun) -> list[dict[str, Any]]:
    return [
        {
            "id": task.id,
            "plan_task_id": plan_task_id(run, task),
            "sequence": task.sequence,
            "agent_type": task.agent_type,
            "status": task.status,
            "attempt_count": task.attempt_count,
            "max_attempts": task.max_attempts,
            "dependencies": list(task.dependencies or []),
            "task_output_hash": _hash(task.task_output or {}),
            "error_hash": _hash(task.error or "") if task.error else None,
        }
        for task in sorted(run.tasks, key=lambda item: (item.sequence, item.id))
    ]


def _material_snapshot(materials: dict[str, ApplicationMaterial | None]) -> dict[str, Any]:
    return {
        material_type: (
            {
                "id": material.id,
                "version": material.version,
                "status": material.status,
                "generator_version": material.generator_version,
                "claims_hash": _hash(material.claims or []),
                "warnings_hash": _hash(material.warnings or []),
                "source_snapshot_hash": _hash(material.source_snapshot or {}),
                "content_hash": hashlib.sha256(material.content.encode("utf-8")).hexdigest(),
            }
            if material
            else None
        )
        for material_type, material in materials.items()
    }


def build_current_handoff_candidate(
    db: Session,
    run: AgentRun,
) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    control = execution_control(run)
    user, application, job, task = _resolve_records(db, run)

    if run.status != "completed":
        blockers.append("bounded_run_not_completed")
    if control.get("scope") != EXECUTION_SCOPE:
        blockers.append("bounded_execution_scope_mismatch")
    if control.get("submission_authorized") is not False:
        blockers.append("bounded_run_submission_flag_invalid")
    if control.get("outreach_authorized") is not False:
        blockers.append("bounded_run_outreach_flag_invalid")
    if control.get("cancellation_requested"):
        blockers.append("bounded_run_cancelled")
    if user is None:
        blockers.append("run_user_missing")
    if task is None:
        blockers.append("application_readiness_task_missing")
    elif task.status != "completed":
        blockers.append("application_readiness_task_not_completed")

    task_output = dict(task.task_output or {}) if task else {}
    if task:
        if task_output.get("ready_for_separate_submission_preflight") is not True:
            blockers.append("bounded_application_readiness_not_confirmed")
        if task_output.get("submission_attempted") is not False:
            blockers.append("bounded_task_submission_attempt_flag_invalid")
        if task_output.get("submission_authorized") is not False:
            blockers.append("bounded_task_submission_authorization_flag_invalid")
        if task_output.get("blockers"):
            blockers.append("bounded_application_readiness_has_blockers")
    if application is None:
        blockers.append("owned_application_missing")
    elif submission_is_closed(application):
        blockers.append("application_submission_closed")
    if job is None:
        blockers.append("application_job_missing")

    blockers = list(dict.fromkeys(blockers))
    if blockers or not user or not application or not job or not task:
        return None, blockers

    materials = _latest_materials(db, application.id)
    material_snapshot = _material_snapshot(materials)
    for material_type, material in materials.items():
        if material is None:
            blockers.append(f"{material_type}_missing")
        elif material.status != "verified":
            blockers.append(f"{material_type}_not_verified")

    task_materials = dict(task_output.get("materials") or {})
    for material_type, material in materials.items():
        task_ref = task_materials.get(material_type)
        if material and isinstance(task_ref, dict):
            if int(task_ref.get("id") or 0) != material.id:
                blockers.append(f"{material_type}_changed_after_bounded_readiness")
            if int(task_ref.get("version") or 0) != material.version:
                blockers.append(f"{material_type}_version_changed_after_bounded_readiness")

    if blockers:
        return None, list(dict.fromkeys(blockers))

    submission_snapshot = build_submission_snapshot(db, application, user, job)
    supervised_preflight = build_supervised_preflight(db, application, user, job)
    ledger = _task_ledger(run)
    safe_preflight = {
        "ready": bool(supervised_preflight.get("ready")),
        "blockers": list(supervised_preflight.get("blockers") or []),
        "platform": supervised_preflight.get("platform"),
        "platform_display_name": supervised_preflight.get("platform_display_name"),
        "adapter_version": supervised_preflight.get("adapter_version"),
        "automation_state": supervised_preflight.get("automation_state"),
        "global_live_submit_enabled": bool(supervised_preflight.get("global_live_submit_enabled")),
        "platform_pilot_enabled": bool(supervised_preflight.get("platform_pilot_enabled")),
        "unresolved_manual_review_count": int(
            supervised_preflight.get("unresolved_manual_review_count") or 0
        ),
    }
    candidate = {
        "version": HANDOFF_VERSION,
        "run_id": run.id,
        "user_id": run.user_id,
        "application_id": application.id,
        "job_id": job.id,
        "employer": submission_snapshot["employer"],
        "role": submission_snapshot["role"],
        "application_url": submission_snapshot["application_url"],
        "execution_scope": EXECUTION_SCOPE,
        "application_task_id": task.id,
        "application_task_plan_id": plan_task_id(run, task),
        "task_ledger_hash": _hash(ledger),
        "task_count": len(ledger),
        "material_snapshot": material_snapshot,
        "automation_state": application.automation_state,
        "application_target_status": application.application_target_status,
        "submission_idempotency_key": submission_snapshot["submission_idempotency_key"],
        "profile_snapshot_hash": submission_snapshot["profile_snapshot_hash"],
        "resume_hash": submission_snapshot["resume_hash"],
        "cover_letter_hash": submission_snapshot["cover_letter_hash"],
        "answer_payload_hash": submission_snapshot["answer_payload_hash"],
        "combined_payload_hash": submission_snapshot["combined_payload_hash"],
        "target_identity_hash": submission_snapshot["target_identity_hash"],
        "supervised_preflight": safe_preflight,
        "submission_authorized": False,
        "approval_issued": False,
        "queue_attempted": False,
    }
    candidate["handoff_hash"] = _hash(candidate)
    return candidate, []


def _stored_handoff(run: AgentRun) -> dict[str, Any] | None:
    value = dict(run.run_context or {}).get(HANDOFF_KEY)
    return dict(value) if isinstance(value, dict) else None


def evaluate_submission_handoff(db: Session, run: AgentRun) -> dict[str, Any]:
    current, blockers = build_current_handoff_candidate(db, run)
    stored = _stored_handoff(run)
    drift_reasons: list[str] = []

    if stored:
        if current is None:
            drift_reasons.extend(f"current:{blocker}" for blocker in blockers)
        else:
            for key in (
                "handoff_hash",
                "task_ledger_hash",
                "combined_payload_hash",
                "profile_snapshot_hash",
                "resume_hash",
                "cover_letter_hash",
                "answer_payload_hash",
                "target_identity_hash",
                "automation_state",
                "application_target_status",
            ):
                if stored.get(key) != current.get(key):
                    drift_reasons.append(f"changed:{key}")

    if not stored:
        status = "not_created"
    elif drift_reasons:
        status = "drifted"
    elif stored.get("reviewed_at"):
        status = "reviewed"
    else:
        status = "created"

    return {
        "run_id": run.id,
        "application_id": (
            current.get("application_id") if current else stored.get("application_id") if stored else None
        ),
        "status": status,
        "exists": stored is not None,
        "eligible": current is not None and not blockers,
        "blockers": blockers,
        "drifted": bool(drift_reasons),
        "drift_reasons": drift_reasons,
        "expected_create_acknowledgment": create_acknowledgment(run.id),
        "expected_review_acknowledgment": review_acknowledgment(run.id),
        "current_snapshot": current,
        "stored_snapshot": stored,
        "submission_authorized": False,
        "approval_issued": False,
        "queue_attempted": False,
    }


def _append_application_event(
    db: Session,
    *,
    application_id: int,
    event_type: str,
    automation_state: str | None,
    payload: dict[str, Any],
) -> None:
    db.add(
        ApplicationEvent(
            application_id=application_id,
            event_type=event_type,
            from_state=automation_state,
            to_state=automation_state,
            payload=payload,
        )
    )


def create_submission_handoff(
    db: Session,
    run: AgentRun,
    *,
    user_id: int,
) -> dict[str, Any]:
    current, blockers = build_current_handoff_candidate(db, run)
    if current is None:
        raise SubmissionHandoffError(
            "Submission handoff is blocked: " + ", ".join(blockers)
        )

    now = _now()
    stored = {
        **current,
        "status": "created",
        "created_at": now.isoformat(),
        "created_by_user_id": user_id,
        "reviewed_at": None,
        "reviewed_by_user_id": None,
        "review_note": None,
    }
    context = dict(run.run_context or {})
    context[HANDOFF_KEY] = stored
    run.run_context = context
    _append_application_event(
        db,
        application_id=int(current["application_id"]),
        event_type="bounded_submission_handoff_created",
        automation_state=current.get("automation_state"),
        payload={
            "agent_run_id": run.id,
            "handoff_version": HANDOFF_VERSION,
            "handoff_hash": current["handoff_hash"],
            "combined_payload_hash": current["combined_payload_hash"],
            "submission_authorized": False,
            "approval_issued": False,
            "queue_attempted": False,
        },
    )
    db.flush()
    return evaluate_submission_handoff(db, run)


def review_submission_handoff(
    db: Session,
    run: AgentRun,
    *,
    user_id: int,
    note: str | None = None,
) -> dict[str, Any]:
    evaluation = evaluate_submission_handoff(db, run)
    if not evaluation["exists"]:
        raise SubmissionHandoffError("Create the submission handoff before reviewing it")
    if evaluation["drifted"]:
        raise SubmissionHandoffError(
            "Submission handoff drifted and must be regenerated before review"
        )
    if not evaluation["eligible"]:
        raise SubmissionHandoffError(
            "Submission handoff is no longer eligible: "
            + ", ".join(evaluation["blockers"])
        )

    stored = dict(evaluation["stored_snapshot"] or {})
    now = _now()
    stored.update(
        {
            "status": "reviewed",
            "reviewed_at": now.isoformat(),
            "reviewed_by_user_id": user_id,
            "review_note": (note or "").strip() or None,
            "submission_authorized": False,
            "approval_issued": False,
            "queue_attempted": False,
        }
    )
    context = dict(run.run_context or {})
    context[HANDOFF_KEY] = stored
    run.run_context = context
    _append_application_event(
        db,
        application_id=int(stored["application_id"]),
        event_type="bounded_submission_handoff_reviewed",
        automation_state=stored.get("automation_state"),
        payload={
            "agent_run_id": run.id,
            "handoff_hash": stored["handoff_hash"],
            "combined_payload_hash": stored["combined_payload_hash"],
            "reviewed_by_user_id": user_id,
            "submission_authorized": False,
            "approval_issued": False,
            "queue_attempted": False,
        },
    )
    db.flush()
    return evaluate_submission_handoff(db, run)
