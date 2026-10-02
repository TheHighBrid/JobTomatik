"""Day 34 Android-first autonomy control-centre service.

This module aggregates existing readiness, queue, blocker, handoff, evidence, and
recovery signals into one account-scoped snapshot. Mutations are deliberately limited
to operator control state and safe pre-submission rejection. There is no submit action.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.handoff import (
    ACTIVE_HANDOFF_STATUSES,
    HandoffActorType,
    HandoffSessionEvent,
    HandoffSessionStatus,
    ManualHandoffSession,
)
from app.models.material import ApplicationMaterial
from app.models.user import User
from app.services.application_state import InvalidApplicationTransition, normalize_state, transition_application_state
from app.services.dead_letter import list_dead_letters
from app.services.operator_autonomy_control import (
    MODE_DRAINING,
    MODE_PAUSED,
    MODE_RUNNING,
    autonomy_control_state,
    set_autonomy_control_mode,
)
from app.services.scheduler_policy import build_scheduler_preview, scheduler_settings


DAY34_CONTROL_CENTRE_VERSION = "android-autonomy-control-centre-v1"
REJECTABLE_AUTOMATION_STATES = frozenset(
    {
        ApplicationAutomationState.preparing.value,
        ApplicationAutomationState.ready_to_apply.value,
        ApplicationAutomationState.needs_review.value,
        ApplicationAutomationState.failed.value,
    }
)
QUEUE_AUTOMATION_STATES = frozenset(
    {
        ApplicationAutomationState.preparing.value,
        ApplicationAutomationState.ready_to_apply.value,
        ApplicationAutomationState.applying.value,
        ApplicationAutomationState.needs_review.value,
        ApplicationAutomationState.submission_uncertain.value,
        ApplicationAutomationState.failed.value,
    }
)


class AutonomyControlError(RuntimeError):
    pass


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _status_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _rejectability(application: Application) -> tuple[bool, str | None]:
    status = _status_value(application.status)
    state = normalize_state(application.automation_state)
    attempts = int(application.submission_attempt_count or 0)
    if status != ApplicationStatus.pending.value:
        return False, f"application_status_{status}_is_not_rejectable"
    if state not in REJECTABLE_AUTOMATION_STATES:
        return False, f"automation_state_{state}_requires_dedicated_review"
    if attempts != 0:
        return False, "submission_attempt_history_requires_dedicated_review"
    return True, None


def _queue_items(db: Session, user_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
    applications = (
        db.query(Application)
        .options(selectinload(Application.job))
        .filter(
            Application.user_id == user_id,
            Application.automation_state.in_(sorted(QUEUE_AUTOMATION_STATES)),
        )
        .order_by(Application.created_at.asc(), Application.id.asc())
        .limit(max(1, min(int(limit), 100)))
        .all()
    )
    rows: list[dict[str, Any]] = []
    for application in applications:
        can_reject, reject_blocker = _rejectability(application)
        job = application.job
        rows.append(
            {
                "application_id": application.id,
                "job_id": application.job_id,
                "title": getattr(job, "title", None) or f"Application {application.id}",
                "company": getattr(job, "company", None),
                "status": _status_value(application.status),
                "automation_state": normalize_state(application.automation_state),
                "submission_attempt_count": int(application.submission_attempt_count or 0),
                "created_at": _iso(application.created_at),
                "updated_at": _iso(application.updated_at),
                "can_reject": can_reject,
                "reject_blocker": reject_blocker,
                "application_path": f"/applications/{application.id}",
            }
        )
    return rows


def _blockers(db: Session, user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    reviews = (
        db.query(ManualReviewTask)
        .join(Application, ManualReviewTask.application_id == Application.id)
        .options(selectinload(ManualReviewTask.application).selectinload(Application.job))
        .filter(
            Application.user_id == user_id,
            ManualReviewTask.status.in_(
                [ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]
            ),
        )
        .order_by(ManualReviewTask.created_at.asc(), ManualReviewTask.id.asc())
        .limit(max(1, min(int(limit), 100)))
        .all()
    )
    rows = []
    for review in reviews:
        application = review.application
        job = application.job if application is not None else None
        rows.append(
            {
                "kind": "manual_review",
                "review_id": review.id,
                "application_id": review.application_id,
                "title": getattr(job, "title", None) or review.summary,
                "company": getattr(job, "company", None),
                "reason_code": review.reason_code,
                "summary": review.summary,
                "status": review.status,
                "created_at": _iso(review.created_at),
                "action_path": f"/applications/{review.application_id}",
            }
        )

    dead_letters = list_dead_letters(db, user_id=user_id, status="open", limit=10)
    for item in dead_letters:
        rows.append(
            {
                "kind": "dead_letter",
                "task_id": item.get("task_id"),
                "run_id": item.get("run_id"),
                "title": item.get("task_name") or "Dead-letter task",
                "reason_code": item.get("failure_class"),
                "summary": item.get("error") or "Bounded task requires recovery review.",
                "status": "open",
                "created_at": item.get("opened_at"),
                "action_path": item.get("recovery_path") or "/recovery",
            }
        )
    rows.sort(key=lambda item: str(item.get("created_at") or ""))
    return rows[: max(1, min(int(limit), 100))]


def _handoffs(db: Session, user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    sessions = (
        db.query(ManualHandoffSession)
        .options(selectinload(ManualHandoffSession.application).selectinload(Application.job))
        .filter(
            ManualHandoffSession.user_id == user_id,
            ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
        )
        .order_by(ManualHandoffSession.created_at.asc(), ManualHandoffSession.id.asc())
        .limit(max(1, min(int(limit), 100)))
        .all()
    )
    rows = []
    for session in sessions:
        application = session.application
        job = application.job if application is not None else None
        rows.append(
            {
                "handoff_id": session.id,
                "public_id": session.public_id,
                "application_id": session.application_id,
                "title": getattr(job, "title", None) or f"Application {session.application_id}",
                "company": getattr(job, "company", None),
                "challenge_type": session.challenge_type,
                "status": session.status,
                "expires_at": _iso(session.expires_at),
                "action_path": "/handoff-review",
            }
        )
    return rows


def _evidence_summary(db: Session, user_id: int) -> dict[str, Any]:
    evidence_rows = (
        db.query(SubmissionEvidence)
        .join(Application, SubmissionEvidence.application_id == Application.id)
        .filter(Application.user_id == user_id)
        .all()
    )
    material_rows = (
        db.query(ApplicationMaterial)
        .filter(ApplicationMaterial.user_id == user_id)
        .all()
    )
    material_statuses = Counter(str(item.status or "unknown") for item in material_rows)
    return {
        "submission_evidence_count": len(evidence_rows),
        "sufficient_submission_evidence_count": sum(bool(item.is_sufficient) for item in evidence_rows),
        "material_count": len(material_rows),
        "verified_material_count": int(material_statuses.get("verified", 0)),
        "material_review_required_count": int(material_statuses.get("needs_review", 0)),
        "material_status_counts": dict(sorted(material_statuses.items())),
        "evidence_path": "/evidence-materials",
    }


def build_autonomy_control_snapshot(
    db: Session,
    user: User,
    *,
    candidate_limit: int = 20,
) -> dict[str, Any]:
    preview = build_scheduler_preview(db, user, candidate_limit=candidate_limit)
    settings = scheduler_settings(user)
    control = autonomy_control_state(user)
    platform_maturities = dict(preview.get("platform_maturities") or {})
    enabled_platforms = [str(item).lower() for item in settings.get("autopilot_enabled_platforms") or []]
    required_maturity = str(preview.get("required_adapter_maturity") or "certified_autonomous")
    adapters = [
        {
            "platform": platform,
            "enabled": True,
            "maturity": platform_maturities.get(platform, "unknown"),
            "unattended_eligible": platform_maturities.get(platform) == required_maturity,
        }
        for platform in enabled_platforms
    ]
    policy = dict(preview.get("user_policy") or {})
    policy_metadata = dict(policy.get("metadata") or {})
    queue = _queue_items(db, user.id)
    blockers = _blockers(db, user.id)
    handoffs = _handoffs(db, user.id)
    evidence = _evidence_summary(db, user.id)
    core = get_settings()

    return {
        "version": DAY34_CONTROL_CENTRE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "operator_control": control,
        "readiness": {
            "scheduler_state": preview.get("scheduler_state"),
            "scheduler_policy_current": bool(preview.get("scheduler_policy_current")),
            "user_policy_allowed": bool(policy.get("allowed")),
            "user_policy_code": policy.get("code"),
            "allowed_candidate_count": int((preview.get("summary") or {}).get("allowed_candidate_count") or 0),
            "required_adapter_maturity": required_maturity,
            "eligible_enabled_adapter_count": sum(item["unattended_eligible"] for item in adapters),
            "ready_for_new_admission": bool(
                control.get("scheduler_admission_allowed")
                and preview.get("scheduler_state") in {"autonomous_candidates_ready", "discovery_ready"}
            ),
        },
        "adapters": adapters,
        "caps": {
            "daily_limit": int(settings.get("auto_apply_daily_limit") or 0),
            "weekly_limit": int(settings.get("auto_apply_weekly_limit") or 0),
            "per_employer_daily_limit": int(settings.get("auto_apply_daily_per_employer_limit") or 0),
            "remaining_daily": int(policy_metadata.get("remaining_daily") or 0),
            "remaining_weekly": int(policy_metadata.get("remaining_weekly") or 0),
            "per_platform_daily_limits": dict(settings.get("autopilot_daily_platform_limits") or {}),
            "quiet_hours_start_utc": settings.get("quiet_hours_start_utc"),
            "quiet_hours_end_utc": settings.get("quiet_hours_end_utc"),
        },
        "queue": {
            "count": len(queue),
            "items": queue,
        },
        "blockers": {
            "count": len(blockers),
            "items": blockers,
        },
        "handoffs": {
            "count": len(handoffs),
            "items": handoffs,
        },
        "evidence": evidence,
        "kill_switches": {
            "operator_mode": control.get("mode"),
            "global_kill_switch": bool(preview.get("global_kill_switch")),
            "global_autopilot_enabled": bool(preview.get("global_autopilot_enabled")),
            "real_submission_enabled": bool(core.allow_real_application_submit),
            "dry_run_mode": bool(settings.get("dry_run_mode", True)),
        },
        "actions": {
            "pause_available": control.get("mode") != MODE_PAUSED,
            "drain_available": control.get("mode") != MODE_DRAINING,
            "resume_available": control.get("mode") != MODE_RUNNING,
            "reject_application_available": True,
            "direct_live_submit_available": False,
        },
        "invariants": {
            "control_centre_cannot_authorize_submission": True,
            "reject_is_canonical_withdrawal_not_employer_rejection": True,
            "pause_blocks_prebrowser_execution": True,
            "drain_blocks_new_admission_but_allows_existing_work": True,
            "resume_reuses_existing_policy_and_maturity_gates": True,
        },
    }


def change_autonomy_mode(
    db: Session,
    user: User,
    *,
    mode: str,
    reason: str | None = None,
) -> dict[str, Any]:
    # ``automation_settings`` is a single JSON value shared with the settings API.
    # Lock and refresh before replacing it so a concurrent settings PATCH cannot
    # commit an older snapshot over a pause or drain action (or vice versa).
    user = (
        db.query(User)
        .filter(User.id == user.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    state = set_autonomy_control_mode(
        user,
        mode=mode,
        actor_user_id=user.id,
        reason=reason,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return state


def reject_application_from_autonomy_queue(
    db: Session,
    user: User,
    *,
    application_id: int,
    reason: str | None = None,
) -> dict[str, Any]:
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user.id)
        .with_for_update()
        .first()
    )
    if application is None:
        raise AutonomyControlError("Application not found")

    can_reject, blocker = _rejectability(application)
    if not can_reject:
        raise AutonomyControlError(blocker or "Application cannot be rejected from autonomy queue")

    detail = (reason or "Rejected from Android autonomy control centre.").strip()[:500]
    try:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.withdrawn,
            "operator_application_rejected",
            {
                "source": "android_autonomy_control_centre",
                "reason": detail,
                "submission_attempt_count": int(application.submission_attempt_count or 0),
                "submission_authorized": False,
            },
        )
    except InvalidApplicationTransition as exc:
        raise AutonomyControlError(str(exc)) from exc
    application.status = ApplicationStatus.withdrawn

    now = datetime.now(timezone.utc)
    open_reviews = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.status.in_(
                [ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]
            ),
        )
        .all()
    )
    for review in open_reviews:
        review.status = ManualReviewStatus.dismissed.value
        review.resolved_at = now
        review.resolution_notes = detail

    active_handoffs = (
        db.query(ManualHandoffSession)
        .filter(
            ManualHandoffSession.application_id == application.id,
            ManualHandoffSession.user_id == user.id,
            ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
        )
        .all()
    )
    for handoff in active_handoffs:
        previous = handoff.status
        handoff.status = HandoffSessionStatus.cancelled.value
        handoff.cancelled_at = now
        handoff.failure_reason = "operator_application_rejected"
        db.add(
            HandoffSessionEvent(
                handoff_session_id=handoff.id,
                application_id=application.id,
                event_type="operator_application_rejected",
                actor_type=HandoffActorType.user.value,
                payload={
                    "from_status": previous,
                    "to_status": HandoffSessionStatus.cancelled.value,
                    "reason": detail,
                },
            )
        )

    log = list(application.automation_log or [])
    log.append(
        {
            "action": "operator_application_rejected",
            "source": "android_autonomy_control_centre",
            "reason": detail,
            "ts": now.isoformat(),
        }
    )
    application.automation_log = log[-100:]
    db.commit()
    db.refresh(application)

    return {
        "application_id": application.id,
        "status": _status_value(application.status),
        "automation_state": normalize_state(application.automation_state),
        "dismissed_review_count": len(open_reviews),
        "cancelled_handoff_count": len(active_handoffs),
        "submission_attempt_count": int(application.submission_attempt_count or 0),
        "submission_idempotency_key": application.submission_idempotency_key,
        "submission_authorized": False,
        "action": "rejected_from_autonomy_queue",
    }


__all__ = [
    "AutonomyControlError",
    "DAY34_CONTROL_CENTRE_VERSION",
    "build_autonomy_control_snapshot",
    "change_autonomy_mode",
    "reject_application_from_autonomy_queue",
]
