"""Read-only roster for current owner-selected Lever Phase B applications.

The roster never ranks jobs, changes application state, creates approvals, queues work,
opens a browser, or submits an application. It exists only to expose deterministic
local eligibility before material preparation.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.services.application_state import normalize_state
from app.services.lever_phase_b_current_intake import INTAKE_SOURCE, SELECTION_POLICY
from app.services.lever_phase_b_reviewed_materials import SUPPORTED_LOCAL_STATES
from app.services.supervised_target_identity import persisted_supervised_target_metadata


def list_current_lever_phase_b_candidates(
    db: Session,
    user: User,
) -> Dict[str, Any]:
    """List current Lever Phase B intake records without mutation or ranking."""

    rows = (
        db.query(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .filter(Application.user_id == user.id)
        .order_by(Application.created_at.asc(), Application.id.asc())
        .all()
    )

    candidates: list[Dict[str, Any]] = []
    for application, job in rows:
        raw = dict(job.raw_data or {})
        if str(raw.get("selection_source") or "") != INTAKE_SOURCE:
            continue

        state = normalize_state(application.automation_state)
        target = persisted_supervised_target_metadata(job)
        target_blockers = [
            str(item).strip()
            for item in target.get("blockers") or []
            if str(item).strip()
        ]
        eligibility_blockers: list[str] = []
        if state not in SUPPORTED_LOCAL_STATES:
            eligibility_blockers.append(
                "automation_state_not_material_preparation_eligible"
            )
        if target.get("verified") is not True:
            eligibility_blockers.append("target_identity_unverified")
        eligibility_blockers.extend(
            f"target_identity:{blocker}" for blocker in target_blockers
        )

        site = str(target.get("site") or "").strip()
        posting_id = str(target.get("posting_id") or "").strip()
        region = str(target.get("region") or "").strip()
        if not site or not posting_id or region not in {"global", "eu"}:
            eligibility_blockers.append("target_identity_incomplete")

        application_url = str(
            target.get("canonical_application_url")
            or raw.get("selected_apply_url")
            or job.url
            or ""
        ).strip()

        unique_blockers = list(dict.fromkeys(eligibility_blockers))
        candidates.append(
            {
                "application_id": application.id,
                "job_id": job.id,
                "employer": str(job.company or "").strip(),
                "role": str(job.title or "").strip(),
                "application_url": application_url,
                "automation_state": state,
                "target_identity_verified": target.get("verified") is True,
                "target_identity_blockers": target_blockers,
                "material_preparation_eligible": not unique_blockers,
                "eligibility_blockers": unique_blockers,
                "created_at": (
                    application.created_at.isoformat()
                    if application.created_at
                    else None
                ),
            }
        )

    return {
        "selection_policy": SELECTION_POLICY,
        "ordering": "application_created_at_ascending_no_ranking",
        "candidate_count": len(candidates),
        "eligible_count": sum(
            1 for item in candidates if item["material_preparation_eligible"]
        ),
        "candidates": candidates,
        "read_only": True,
        "approval_issued": False,
        "submission_queued": False,
        "runtime_flags_changed": False,
    }


__all__ = ["list_current_lever_phase_b_candidates"]
