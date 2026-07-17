"""Technical roster for the Greenhouse supervised pilot.

The roster never ranks jobs, chooses an employer, issues an approval, or queues a
submission. It lists the authenticated user's Greenhouse applications in stable
creation order and separates structural blockers from the two disabled-by-default
execution flags. The user still selects and approves each exact application.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationAutomationState, ApplicationEvent
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.operations_policy import platform_key_for_url
from app.services.supervised_submission import build_supervised_preflight


PHASE_B_TARGET = 10
EXECUTION_FLAG_BLOCKERS = {
    "global_live_submit_disabled",
    "greenhouse_supervised_pilot_disabled",
}


def _target_url(job: Job) -> str:
    raw = dict(job.raw_data or {})
    return str(raw.get("selected_apply_url") or job.url or "").strip()


def _active_approval(db: Session, application_id: int) -> Optional[SubmissionApproval]:
    return (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.status == SubmissionApprovalStatus.active.value,
        )
        .order_by(SubmissionApproval.created_at.desc(), SubmissionApproval.id.desc())
        .first()
    )


def _ingested_application_ids(db: Session, user_id: int) -> set[int]:
    rows = (
        db.query(ApplicationEvent.application_id)
        .join(Application, ApplicationEvent.application_id == Application.id)
        .filter(
            Application.user_id == user_id,
            ApplicationEvent.event_type == "supervised_pilot_record_ingested",
        )
        .all()
    )
    return {int(row[0]) for row in rows}


def build_supervised_pilot_roster(
    db: Session,
    user: User,
    *,
    readiness: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a non-ranked, technical eligibility roster for one user."""

    readiness_payload = dict(readiness or {})
    summary = dict(readiness_payload.get("summary") or {})
    confirmed_count = int(summary.get("supervised_confirmed_count") or 0)
    qualifying_dry_runs = int(summary.get("qualifying_dry_run_count") or 0)
    distinct_employers = int(summary.get("distinct_dry_run_employer_count") or 0)

    applications = (
        db.query(Application)
        .filter(Application.user_id == user.id)
        .order_by(Application.created_at.asc(), Application.id.asc())
        .all()
    )
    ingested_ids = _ingested_application_ids(db, user.id)
    candidates = []
    for application in applications:
        job = db.query(Job).filter(Job.id == application.job_id).first()
        if not job or platform_key_for_url(_target_url(job)) != "greenhouse":
            continue

        preflight = build_supervised_preflight(db, application, user, job)
        structural_blockers = [
            blocker
            for blocker in preflight["blockers"]
            if blocker not in EXECUTION_FLAG_BLOCKERS
        ]
        approval = _active_approval(db, application.id)
        state = str(
            application.automation_state
            or ApplicationAutomationState.preparing.value
        )
        already_confirmed = state == ApplicationAutomationState.confirmed.value
        already_ingested = application.id in ingested_ids

        if already_ingested:
            roster_status = "recorded_in_pilot_ledger"
        elif already_confirmed:
            roster_status = "confirmed_pending_ledger_ingestion"
        elif not structural_blockers:
            roster_status = "available_for_user_review"
        else:
            roster_status = "blocked"

        candidates.append(
            {
                "application_id": application.id,
                "job_id": job.id,
                "employer": preflight["employer"],
                "role": preflight["role"],
                "application_url": preflight["application_url"],
                "automation_state": state,
                "roster_status": roster_status,
                "technical_ready": not structural_blockers,
                "technical_blockers": structural_blockers,
                "execution_ready": bool(preflight["ready"]),
                "execution_blockers": list(preflight["blockers"]),
                "unresolved_manual_review_count": preflight[
                    "unresolved_manual_review_count"
                ],
                "cover_letter_present": preflight["cover_letter_present"],
                "resume_filename": preflight["resume_filename"],
                "policy_count": preflight["policy_count"],
                "active_approval_reference": approval.reference if approval else None,
                "active_approval_expires_at": (
                    approval.expires_at.isoformat() if approval and approval.expires_at else None
                ),
                "created_at": (
                    application.created_at.isoformat()
                    if application.created_at
                    else None
                ),
                "already_confirmed": already_confirmed,
                "already_ingested": already_ingested,
            }
        )

    return {
        "selection_policy": "user_selected_exact_application",
        "ordering": "application_created_at_ascending_no_ranking",
        "phase_a": {
            "qualifying_dry_run_count": qualifying_dry_runs,
            "distinct_employer_count": distinct_employers,
            "complete": qualifying_dry_runs >= 30 and distinct_employers >= 30,
        },
        "phase_b": {
            "confirmed_count": confirmed_count,
            "target": PHASE_B_TARGET,
            "remaining": max(0, PHASE_B_TARGET - confirmed_count),
            "complete": confirmed_count >= PHASE_B_TARGET,
        },
        "execution_flags": {
            "global_live_submit_enabled": bool(
                candidates[0]["execution_ready"]
                or any(
                    "global_live_submit_disabled" not in item["execution_blockers"]
                    for item in candidates
                )
            ) if candidates else False,
            "greenhouse_supervised_pilot_enabled": bool(
                candidates[0]["execution_ready"]
                or any(
                    "greenhouse_supervised_pilot_disabled"
                    not in item["execution_blockers"]
                    for item in candidates
                )
            ) if candidates else False,
        },
        "candidate_count": len(candidates),
        "technically_ready_count": sum(
            1 for item in candidates if item["technical_ready"]
        ),
        "candidates": candidates,
        "readiness_available": bool(summary),
    }


__all__ = ["PHASE_B_TARGET", "build_supervised_pilot_roster"]
