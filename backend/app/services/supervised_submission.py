"""Exact-payload approval gate for Greenhouse supervised submissions.

This service never submits an application. It creates short-lived, one-time
approval records bound to an exact employer, role, URL, idempotency key, profile,
resume, cover letter, and approved answer-policy payload. Any mutation, expiry,
open review task, or feature-flag change invalidates the approval.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.submission_approval import (
    SubmissionApproval,
    SubmissionApprovalStatus,
)
from app.models.user import User
from app.services.answer_policy import load_runtime_policies
from app.services.operations_policy import platform_key_for_url


settings = get_settings()
SUPPORTED_PLATFORM = "greenhouse"


class SupervisedSubmissionApprovalError(ValueError):
    pass


class SupervisedSubmissionApprovalExpired(SupervisedSubmissionApprovalError):
    pass


class SupervisedSubmissionApprovalMismatch(SupervisedSubmissionApprovalError):
    pass


def _now() -> datetime:
    return datetime.utcnow()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _hash_file(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_url(job: Job) -> str:
    raw = dict(job.raw_data or {})
    return str(raw.get("selected_apply_url") or job.url or "").strip()


def _active_review_count(db: Session, application_id: int) -> int:
    return (
        db.query(ManualReviewTask.id)
        .filter(
            ManualReviewTask.application_id == application_id,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .count()
    )


def build_submission_snapshot(
    db: Session,
    application: Application,
    user: User,
    job: Job,
) -> Dict[str, Any]:
    target_url = _target_url(job)
    platform = platform_key_for_url(target_url)
    profile_payload = {
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "address": user.address,
        "linkedin_url": user.linkedin_url,
        "github_url": user.github_url,
        "portfolio_url": user.portfolio_url,
        "profile_data": dict(user.profile_data or {}),
    }
    policies = load_runtime_policies(
        db,
        user.id,
        target_url=target_url,
        company=str(job.company or ""),
    )
    resume_hash = _hash_file(user.resume_path)
    cover_letter_hash = _hash_value(application.cover_letter or "")
    answer_payload_hash = _hash_value(policies)
    profile_snapshot_hash = _hash_value(profile_payload)
    combined_payload_hash = _hash_value(
        {
            "application_id": application.id,
            "user_id": user.id,
            "job_id": job.id,
            "employer": str(job.company or "").strip(),
            "role": str(job.title or "").strip(),
            "application_url": target_url,
            "platform": platform,
            "submission_idempotency_key": application.submission_idempotency_key,
            "profile_snapshot_hash": profile_snapshot_hash,
            "resume_hash": resume_hash,
            "cover_letter_hash": cover_letter_hash,
            "answer_payload_hash": answer_payload_hash,
        }
    )
    return {
        "application_id": application.id,
        "user_id": user.id,
        "job_id": job.id,
        "employer": str(job.company or "").strip(),
        "role": str(job.title or "").strip(),
        "application_url": target_url,
        "platform": platform,
        "submission_idempotency_key": str(
            application.submission_idempotency_key or ""
        ).strip(),
        "profile_snapshot_hash": profile_snapshot_hash,
        "resume_hash": resume_hash,
        "cover_letter_hash": cover_letter_hash,
        "answer_payload_hash": answer_payload_hash,
        "combined_payload_hash": combined_payload_hash,
        "policy_count": len(policies),
        "cover_letter_present": bool((application.cover_letter or "").strip()),
        "resume_filename": Path(user.resume_path).name if user.resume_path else None,
    }


def build_supervised_preflight(
    db: Session,
    application: Application,
    user: User,
    job: Job,
) -> Dict[str, Any]:
    snapshot = build_submission_snapshot(db, application, user, job)
    state = application.automation_state or ApplicationAutomationState.preparing.value
    open_reviews = _active_review_count(db, application.id)
    live_enabled = bool(settings.allow_real_application_submit)
    pilot_enabled = bool(
        getattr(settings, "greenhouse_supervised_pilot_enabled", False)
    )

    blockers = []
    if not live_enabled:
        blockers.append("global_live_submit_disabled")
    if not pilot_enabled:
        blockers.append("greenhouse_supervised_pilot_disabled")
    if snapshot["platform"] != SUPPORTED_PLATFORM:
        blockers.append("unsupported_platform")
    if state != ApplicationAutomationState.ready_to_apply.value:
        blockers.append("application_not_ready_to_apply")
    if open_reviews:
        blockers.append("unresolved_manual_reviews")
    if not snapshot["application_url"]:
        blockers.append("missing_application_url")
    if not snapshot["submission_idempotency_key"]:
        blockers.append("missing_submission_idempotency_key")
    if not snapshot["resume_hash"]:
        blockers.append("resume_missing_or_unreadable")

    return {
        "ready": not blockers,
        "blockers": blockers,
        "application_id": application.id,
        "platform": snapshot["platform"],
        "employer": snapshot["employer"],
        "role": snapshot["role"],
        "application_url": snapshot["application_url"],
        "automation_state": state,
        "unresolved_manual_review_count": open_reviews,
        "global_live_submit_enabled": live_enabled,
        "platform_pilot_enabled": pilot_enabled,
        "submission_idempotency_key": snapshot["submission_idempotency_key"],
        "profile_snapshot_hash": snapshot["profile_snapshot_hash"],
        "resume_hash": snapshot["resume_hash"],
        "cover_letter_hash": snapshot["cover_letter_hash"],
        "answer_payload_hash": snapshot["answer_payload_hash"],
        "combined_payload_hash": snapshot["combined_payload_hash"],
        "policy_count": snapshot["policy_count"],
        "cover_letter_present": snapshot["cover_letter_present"],
        "resume_filename": snapshot["resume_filename"],
    }


def _expire_or_revoke_prior_approvals(
    db: Session,
    application_id: int,
    now: datetime,
) -> None:
    approvals = (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.status == SubmissionApprovalStatus.active.value,
        )
        .with_for_update()
        .all()
    )
    for approval in approvals:
        if approval.expires_at <= now:
            approval.status = SubmissionApprovalStatus.expired.value
        else:
            approval.status = SubmissionApprovalStatus.revoked.value
            approval.revoked_at = now
            approval.approval_metadata = {
                **dict(approval.approval_metadata or {}),
                "revocation_reason": "superseded_by_new_approval",
            }


def issue_supervised_approval(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    confirm_employer: str,
    confirm_role: str,
    confirm_application_url: str,
    confirm_final_submit: bool,
    expires_in_minutes: Optional[int] = None,
    notes: Optional[str] = None,
) -> SubmissionApproval:
    preflight = build_supervised_preflight(db, application, user, job)
    if not preflight["ready"]:
        raise SupervisedSubmissionApprovalError(
            "Supervised submission preflight is blocked: "
            + ", ".join(preflight["blockers"])
        )
    if confirm_final_submit is not True:
        raise SupervisedSubmissionApprovalError(
            "confirm_final_submit must be explicitly true"
        )
    confirmations = {
        "employer": (confirm_employer.strip(), preflight["employer"]),
        "role": (confirm_role.strip(), preflight["role"]),
        "application_url": (
            confirm_application_url.strip(),
            preflight["application_url"],
        ),
    }
    mismatches = [
        field for field, (provided, expected) in confirmations.items()
        if provided != expected
    ]
    if mismatches:
        raise SupervisedSubmissionApprovalMismatch(
            "Explicit confirmation did not match: " + ", ".join(mismatches)
        )

    configured_ttl = int(
        getattr(settings, "supervised_approval_ttl_minutes", 20)
    )
    max_ttl = int(
        getattr(settings, "supervised_approval_max_ttl_minutes", 60)
    )
    ttl = expires_in_minutes if expires_in_minutes is not None else configured_ttl
    ttl = max(1, min(int(ttl), max_ttl))
    now = _now()
    _expire_or_revoke_prior_approvals(db, application.id, now)

    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform=SUPPORTED_PLATFORM,
        status=SubmissionApprovalStatus.active.value,
        employer=preflight["employer"],
        role=preflight["role"],
        application_url=preflight["application_url"],
        submission_idempotency_key=preflight["submission_idempotency_key"],
        profile_snapshot_hash=preflight["profile_snapshot_hash"],
        resume_hash=preflight["resume_hash"],
        cover_letter_hash=preflight["cover_letter_hash"],
        answer_payload_hash=preflight["answer_payload_hash"],
        combined_payload_hash=preflight["combined_payload_hash"],
        approved_at=now,
        expires_at=now + timedelta(minutes=ttl),
        notes=notes,
        approval_metadata={
            "approval_source": "authenticated_user_api",
            "confirm_final_submit": True,
            "policy_count": preflight["policy_count"],
            "cover_letter_present": preflight["cover_letter_present"],
            "resume_filename": preflight["resume_filename"],
            "unresolved_manual_review_count": 0,
            "global_live_submit_enabled": True,
            "platform_pilot_enabled": True,
        },
    )
    db.add(approval)
    db.flush()
    db.add(ApplicationEvent(
        application_id=application.id,
        event_type="supervised_submission_approval_issued",
        from_state=application.automation_state,
        to_state=application.automation_state,
        payload={
            "approval_reference": approval.reference,
            "platform": approval.platform,
            "employer": approval.employer,
            "role": approval.role,
            "application_url": approval.application_url,
            "expires_at": approval.expires_at.isoformat(),
            "combined_payload_hash": approval.combined_payload_hash,
        },
    ))
    return approval


def _load_owned_approval(
    db: Session,
    *,
    application_id: int,
    user_id: int,
    reference: str,
    for_update: bool = False,
) -> SubmissionApproval:
    query = db.query(SubmissionApproval).filter(
        SubmissionApproval.application_id == application_id,
        SubmissionApproval.user_id == user_id,
        SubmissionApproval.reference == reference,
    )
    if for_update:
        query = query.with_for_update()
    approval = query.first()
    if not approval:
        raise SupervisedSubmissionApprovalError("Submission approval not found")
    return approval


def validate_supervised_approval(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    reference: str,
    consume: bool = False,
) -> SubmissionApproval:
    approval = _load_owned_approval(
        db,
        application_id=application.id,
        user_id=user.id,
        reference=reference,
        for_update=consume,
    )
    now = _now()
    if approval.status != SubmissionApprovalStatus.active.value:
        raise SupervisedSubmissionApprovalError(
            f"Submission approval is {approval.status}, not active"
        )
    if approval.expires_at <= now:
        approval.status = SubmissionApprovalStatus.expired.value
        raise SupervisedSubmissionApprovalExpired("Submission approval has expired")

    preflight = build_supervised_preflight(db, application, user, job)
    if not preflight["ready"]:
        raise SupervisedSubmissionApprovalError(
            "Supervised submission preflight is blocked: "
            + ", ".join(preflight["blockers"])
        )

    expected: Mapping[str, Any] = {
        "platform": preflight["platform"],
        "employer": preflight["employer"],
        "role": preflight["role"],
        "application_url": preflight["application_url"],
        "submission_idempotency_key": preflight["submission_idempotency_key"],
        "profile_snapshot_hash": preflight["profile_snapshot_hash"],
        "resume_hash": preflight["resume_hash"],
        "cover_letter_hash": preflight["cover_letter_hash"],
        "answer_payload_hash": preflight["answer_payload_hash"],
        "combined_payload_hash": preflight["combined_payload_hash"],
    }
    mismatches = [
        field for field, value in expected.items()
        if getattr(approval, field) != value
    ]
    if mismatches:
        approval.status = SubmissionApprovalStatus.revoked.value
        approval.revoked_at = now
        approval.approval_metadata = {
            **dict(approval.approval_metadata or {}),
            "revocation_reason": "approved_payload_changed",
            "mismatched_fields": mismatches,
        }
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="supervised_submission_approval_invalidated",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "approval_reference": approval.reference,
                "mismatched_fields": mismatches,
            },
        ))
        raise SupervisedSubmissionApprovalMismatch(
            "Approved submission payload changed: " + ", ".join(mismatches)
        )

    if consume:
        approval.status = SubmissionApprovalStatus.consumed.value
        approval.consumed_at = now
        approval.approval_metadata = {
            **dict(approval.approval_metadata or {}),
            "consumed_for_attempt": (application.submission_attempt_count or 0) + 1,
        }
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="supervised_submission_approval_consumed",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "approval_reference": approval.reference,
                "attempt": (application.submission_attempt_count or 0) + 1,
                "combined_payload_hash": approval.combined_payload_hash,
            },
        ))
    return approval


def revoke_supervised_approval(
    db: Session,
    application: Application,
    user: User,
    *,
    reference: str,
    reason: str = "revoked_by_user",
) -> SubmissionApproval:
    approval = _load_owned_approval(
        db,
        application_id=application.id,
        user_id=user.id,
        reference=reference,
        for_update=True,
    )
    if approval.status == SubmissionApprovalStatus.active.value:
        approval.status = SubmissionApprovalStatus.revoked.value
        approval.revoked_at = _now()
        approval.approval_metadata = {
            **dict(approval.approval_metadata or {}),
            "revocation_reason": reason,
        }
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="supervised_submission_approval_revoked",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "approval_reference": approval.reference,
                "reason": reason,
            },
        ))
    return approval


def approval_safe_dict(approval: SubmissionApproval) -> Dict[str, Any]:
    return {
        "reference": approval.reference,
        "application_id": approval.application_id,
        "user_id": approval.user_id,
        "platform": approval.platform,
        "status": approval.status,
        "employer": approval.employer,
        "role": approval.role,
        "application_url": approval.application_url,
        "submission_idempotency_key": approval.submission_idempotency_key,
        "profile_snapshot_hash": approval.profile_snapshot_hash,
        "resume_hash": approval.resume_hash,
        "cover_letter_hash": approval.cover_letter_hash,
        "answer_payload_hash": approval.answer_payload_hash,
        "combined_payload_hash": approval.combined_payload_hash,
        "approved_at": approval.approved_at,
        "expires_at": approval.expires_at,
        "consumed_at": approval.consumed_at,
        "revoked_at": approval.revoked_at,
        "notes": approval.notes,
        "approval_metadata": dict(approval.approval_metadata or {}),
        "created_at": approval.created_at,
        "updated_at": approval.updated_at,
    }


__all__ = [
    "SUPPORTED_PLATFORM",
    "SupervisedSubmissionApprovalError",
    "SupervisedSubmissionApprovalExpired",
    "SupervisedSubmissionApprovalMismatch",
    "approval_safe_dict",
    "build_submission_snapshot",
    "build_supervised_preflight",
    "issue_supervised_approval",
    "revoke_supervised_approval",
    "validate_supervised_approval",
]
