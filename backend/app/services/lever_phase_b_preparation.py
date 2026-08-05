"""Read-only local preparation stages for retained Lever Phase B candidates.

This module inspects only user-owned JobTomatik records. It never resolves an
external target, rebuilds evidence, generates materials, issues an approval,
queues a task, opens a browser, or contacts Lever.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.material import ApplicationMaterial
from app.models.submission_approval import (
    SubmissionApproval,
    SubmissionApprovalStatus,
)
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User


SUBMISSION_STATES = {
    ApplicationAutomationState.applying.value,
    ApplicationAutomationState.submission_uncertain.value,
    ApplicationAutomationState.submitted.value,
    ApplicationAutomationState.confirmed.value,
    ApplicationAutomationState.failed.value,
    ApplicationAutomationState.withdrawn.value,
}


def _latest_material(
    db: Session,
    application_id: int,
    material_type: str,
) -> Optional[ApplicationMaterial]:
    return (
        db.query(ApplicationMaterial)
        .filter(
            ApplicationMaterial.application_id == application_id,
            ApplicationMaterial.material_type == material_type,
        )
        .order_by(
            ApplicationMaterial.version.desc(),
            ApplicationMaterial.id.desc(),
        )
        .first()
    )


def _open_review_count(db: Session, application_id: int) -> int:
    return (
        db.query(ManualReviewTask.id)
        .filter(
            ManualReviewTask.application_id == application_id,
            ManualReviewTask.status.in_(
                [
                    ManualReviewStatus.open.value,
                    ManualReviewStatus.in_progress.value,
                ]
            ),
        )
        .count()
    )


def _latest_active_approval(
    db: Session,
    application_id: int,
) -> Optional[SubmissionApproval]:
    approvals = (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.platform == "lever",
            SubmissionApproval.status == SubmissionApprovalStatus.active.value,
        )
        .order_by(
            SubmissionApproval.created_at.desc(),
            SubmissionApproval.id.desc(),
        )
        .all()
    )
    now_aware = datetime.now(timezone.utc)
    for approval in approvals:
        expires_at = approval.expires_at
        if expires_at is None:
            continue
        now = now_aware if expires_at.tzinfo else now_aware.replace(tzinfo=None)
        if expires_at > now:
            return approval
    return None


def _latest_attempt(
    db: Session,
    application_id: int,
) -> Optional[SubmissionAttempt]:
    return (
        db.query(SubmissionAttempt)
        .filter(SubmissionAttempt.application_id == application_id)
        .order_by(SubmissionAttempt.id.desc())
        .first()
    )


def _material_snapshot(material: Optional[ApplicationMaterial]) -> Dict[str, Any]:
    return {
        "status": material.status if material else None,
        "version": material.version if material else None,
    }


def _base_stage(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        **dict(candidate),
        "preparation_stage": "not_materialized",
        "preparation_blockers": ["materialize_preparation_record"],
        "preparation_next_action": "materialize",
        "resume_present": False,
        "application_cover_letter_present": False,
        "cover_letter_material_status": None,
        "cover_letter_material_version": None,
        "resume_summary_material_status": None,
        "resume_summary_material_version": None,
        "open_review_count": 0,
        "active_approval_reference": None,
        "active_approval_expires_at": None,
        "latest_attempt_reference": None,
        "latest_attempt_status": None,
    }


def enrich_lever_phase_b_preparation_status(
    db: Session,
    user: User,
    launch_status: Mapping[str, Any],
) -> Dict[str, Any]:
    """Add deterministic local preparation stages to a verified launch status."""

    candidates = []
    for raw_candidate in launch_status.get("candidates") or []:
        candidate = _base_stage(raw_candidate)
        application_id = candidate.get("materialized_application_id")
        if not candidate.get("materialized") or not application_id:
            candidates.append(candidate)
            continue

        application = (
            db.query(Application)
            .filter(
                Application.id == int(application_id),
                Application.user_id == user.id,
            )
            .first()
        )
        if application is None:
            candidate["materialized"] = False
            candidate["materialized_application_id"] = None
            candidate["job_id"] = None
            candidates.append(candidate)
            continue

        cover_letter = _latest_material(db, application.id, "cover_letter")
        resume_summary = _latest_material(db, application.id, "resume_summary")
        cover_snapshot = _material_snapshot(cover_letter)
        resume_snapshot = _material_snapshot(resume_summary)
        open_reviews = _open_review_count(db, application.id)
        approval = _latest_active_approval(db, application.id)
        attempt = _latest_attempt(db, application.id)
        state = str(
            application.automation_state
            or ApplicationAutomationState.preparing.value
        )
        status_value = str(
            getattr(application.status, "value", application.status)
            or ApplicationStatus.pending.value
        )

        candidate.update(
            {
                "automation_state": state,
                "resume_present": bool(str(user.resume_path or "").strip()),
                "application_cover_letter_present": bool(
                    str(application.cover_letter or "").strip()
                ),
                "cover_letter_material_status": cover_snapshot["status"],
                "cover_letter_material_version": cover_snapshot["version"],
                "resume_summary_material_status": resume_snapshot["status"],
                "resume_summary_material_version": resume_snapshot["version"],
                "open_review_count": open_reviews,
                "active_approval_reference": (
                    approval.reference if approval else None
                ),
                "active_approval_expires_at": (
                    approval.expires_at.isoformat()
                    if approval and approval.expires_at
                    else None
                ),
                "latest_attempt_reference": (
                    attempt.reference if attempt else None
                ),
                "latest_attempt_status": attempt.status if attempt else None,
            }
        )

        submission_state = bool(
            attempt
            or state in SUBMISSION_STATES
            or status_value != ApplicationStatus.pending.value
        )
        if submission_state:
            candidate.update(
                {
                    "preparation_stage": "submission_state_present",
                    "preparation_blockers": [],
                    "preparation_next_action": "inspect_submission_state",
                }
            )
            candidates.append(candidate)
            continue

        review_blockers = []
        if open_reviews:
            review_blockers.append("open_manual_review_tasks")
        if state == ApplicationAutomationState.needs_review.value:
            review_blockers.append("application_needs_review")
        if cover_letter and cover_letter.status == "needs_review":
            review_blockers.append("cover_letter_review_required")
        if resume_summary and resume_summary.status == "needs_review":
            review_blockers.append("resume_summary_review_required")
        if review_blockers:
            candidate.update(
                {
                    "preparation_stage": "review_required",
                    "preparation_blockers": list(dict.fromkeys(review_blockers)),
                    "preparation_next_action": "resolve_review",
                }
            )
            candidates.append(candidate)
            continue

        if approval:
            candidate.update(
                {
                    "preparation_stage": "active_approval_present",
                    "preparation_blockers": [],
                    "preparation_next_action": "review_active_approval",
                }
            )
            candidates.append(candidate)
            continue

        material_blockers = []
        if not candidate["resume_present"]:
            material_blockers.append("resume_required")
        if cover_letter is None or cover_letter.status != "verified":
            material_blockers.append("verified_cover_letter_required")
        if not candidate["application_cover_letter_present"]:
            material_blockers.append("application_cover_letter_required")
        if resume_summary is None or resume_summary.status != "verified":
            material_blockers.append("verified_resume_summary_required")
        if state != ApplicationAutomationState.ready_to_apply.value:
            material_blockers.append("application_not_ready_to_apply")
        if material_blockers:
            candidate.update(
                {
                    "preparation_stage": "verified_materials_required",
                    "preparation_blockers": material_blockers,
                    "preparation_next_action": "build_verified_materials",
                }
            )
            candidates.append(candidate)
            continue

        candidate.update(
            {
                "preparation_stage": "fresh_preflight_required",
                "preparation_blockers": [],
                "preparation_next_action": "open_fresh_preflight",
            }
        )
        candidates.append(candidate)

    result = dict(launch_status)
    result["candidates"] = candidates
    result["preparation_stage_counts"] = {
        stage: sum(
            1 for candidate in candidates if candidate["preparation_stage"] == stage
        )
        for stage in (
            "not_materialized",
            "verified_materials_required",
            "review_required",
            "fresh_preflight_required",
            "active_approval_present",
            "submission_state_present",
        )
    }
    return result


__all__ = ["enrich_lever_phase_b_preparation_status"]
