"""Exact human-final-click approval for supervised Phase B submissions.

This lane never gives JobTomatik permission to click the final submit control, never
creates a SubmissionAttempt, and never enables the live-submit/pilot/autopilot flags.
It binds one short-lived approval to the exact payload, target, and retained browser
handoff that the authenticated owner will inspect and operate directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import (
    ACTIVE_HANDOFF_STATUSES,
    HandoffChallengeType,
    ManualHandoffSession,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.application_state import normalize_state, transition_application_state
from app.services.operations_settings import get_operations_settings
from app.services.supervised_platforms import get_supervised_platform_policy
from app.services.supervised_submission import build_supervised_preflight


_core_settings = get_settings()


class _OperatorSettingsProxy:
    """Compatibility view for core settings plus the canonical operations autopilot flag."""

    def __getattr__(self, name: str) -> Any:
        if name == "autopilot_enabled":
            return bool(get_operations_settings().autopilot_enabled)
        return getattr(_core_settings, name)


settings = _OperatorSettingsProxy()
OPERATOR_ASSISTED_APPROVAL_SOURCE = "authenticated_user_operator_assisted"


class OperatorAssistedSubmissionError(ValueError):
    pass


class OperatorAssistedApprovalExpired(OperatorAssistedSubmissionError):
    pass


class OperatorAssistedApprovalMismatch(OperatorAssistedSubmissionError):
    pass


def _now() -> datetime:
    return datetime.utcnow()


def _operator_execution_blockers(preflight: Mapping[str, Any]) -> set[str]:
    blockers = {"global_live_submit_disabled"}
    policy = get_supervised_platform_policy(str(preflight.get("platform") or ""))
    if policy is not None:
        blockers.add(policy.pilot_disabled_blocker)
    return blockers


def _active_final_submit_boundary(
    db: Session,
    application: Application,
    *,
    public_id: Optional[str] = None,
) -> Optional[ManualHandoffSession]:
    reviews = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .order_by(ManualReviewTask.created_at.desc(), ManualReviewTask.id.desc())
        .all()
    )
    if len(reviews) != 1:
        return None
    review = reviews[0]
    if review.reason_code != ManualReviewReason.operator_final_submit_required.value:
        return None

    query = db.query(ManualHandoffSession).filter(
        ManualHandoffSession.application_id == application.id,
        ManualHandoffSession.manual_review_id == review.id,
        ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
        ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
    )
    if public_id:
        query = query.filter(ManualHandoffSession.public_id == public_id)
    sessions = query.order_by(
        ManualHandoffSession.created_at.desc(),
        ManualHandoffSession.id.desc(),
    ).all()
    return sessions[0] if len(sessions) == 1 else None


def get_operator_final_submit_boundary(
    db: Session,
    application: Application,
) -> Optional[ManualHandoffSession]:
    return _active_final_submit_boundary(db, application)


def build_operator_assisted_preflight(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Reuse structural supervised checks while insisting automation authority is off."""

    base = build_supervised_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )
    policy = get_supervised_platform_policy(base.get("platform"))
    boundary = _active_final_submit_boundary(db, application)
    operations = get_operations_settings()
    autopilot_enabled = bool(operations.autopilot_enabled)
    ignored = _operator_execution_blockers(base)
    if boundary is not None:
        ignored.update({"application_not_ready_to_apply", "unresolved_manual_reviews"})

    blockers = [
        str(item)
        for item in base.get("blockers") or []
        if str(item) not in ignored
    ]

    if base.get("global_live_submit_enabled") is not False:
        blockers.append("operator_assisted_requires_global_submit_disabled")
    if policy is not None and base.get("platform_pilot_enabled") is not False:
        blockers.append("operator_assisted_requires_platform_pilot_disabled")
    if autopilot_enabled:
        blockers.append("operator_assisted_requires_autopilot_disabled")

    blockers = list(dict.fromkeys(blockers))
    return {
        **base,
        "ready": not blockers,
        "blockers": blockers,
        "submission_mode": "operator_assisted_final_click",
        "operator_final_click_required": True,
        "automated_submission_authorized": False,
        "queue_submission_authorized": False,
        "autopilot_enabled": autopilot_enabled,
        "operator_final_submit_boundary": boundary is not None,
        "operator_handoff_public_id": boundary.public_id if boundary else None,
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
                "revocation_reason": "superseded_by_operator_assisted_approval",
            }


def _consumed_operator_approval_for_handoff(
    db: Session,
    *,
    application_id: int,
    user_id: int,
    handoff_public_id: str,
) -> Optional[SubmissionApproval]:
    approvals = (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.user_id == user_id,
            SubmissionApproval.status == SubmissionApprovalStatus.consumed.value,
        )
        .order_by(SubmissionApproval.consumed_at.desc(), SubmissionApproval.id.desc())
        .all()
    )
    for approval in approvals:
        metadata = dict(approval.approval_metadata or {})
        if (
            metadata.get("approval_source") == OPERATOR_ASSISTED_APPROVAL_SOURCE
            and metadata.get("handoff_public_id") == handoff_public_id
        ):
            return approval
    return None


def issue_operator_assisted_approval(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    handoff_public_id: str,
    confirm_employer: str,
    confirm_role: str,
    confirm_application_url: str,
    confirm_operator_final_click: bool,
    expires_in_minutes: Optional[int] = None,
    notes: Optional[str] = None,
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> SubmissionApproval:
    boundary = _active_final_submit_boundary(
        db,
        application,
        public_id=str(handoff_public_id or "").strip(),
    )
    if boundary is None:
        raise OperatorAssistedSubmissionError(
            "Prepare and retain the exact ready-to-submit application before approval."
        )
    if _consumed_operator_approval_for_handoff(
        db,
        application_id=application.id,
        user_id=user.id,
        handoff_public_id=boundary.public_id,
    ) is not None:
        raise OperatorAssistedSubmissionError(
            "This retained final-submit handoff already consumed an owner approval. "
            "A second approval is forbidden."
        )

    preflight = build_operator_assisted_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )
    if not preflight["ready"]:
        raise OperatorAssistedSubmissionError(
            "Operator-assisted preflight is blocked: " + ", ".join(preflight["blockers"])
        )
    if preflight.get("operator_handoff_public_id") != boundary.public_id:
        raise OperatorAssistedSubmissionError("Retained final-submit handoff changed")
    if confirm_operator_final_click is not True:
        raise OperatorAssistedSubmissionError(
            "confirm_operator_final_click must be explicitly true"
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
        field
        for field, (provided, expected) in confirmations.items()
        if provided != expected
    ]
    if mismatches:
        raise OperatorAssistedApprovalMismatch(
            "Explicit confirmation did not match: " + ", ".join(mismatches)
        )

    policy = get_supervised_platform_policy(preflight["platform"])
    if policy is None:
        raise OperatorAssistedSubmissionError("Unsupported supervised platform")

    configured_ttl = int(getattr(settings, "supervised_approval_ttl_minutes", 20))
    max_ttl = int(getattr(settings, "supervised_approval_max_ttl_minutes", 60))
    ttl = expires_in_minutes if expires_in_minutes is not None else configured_ttl
    ttl = max(1, min(int(ttl), max_ttl))
    now = _now()
    _expire_or_revoke_prior_approvals(db, application.id, now)

    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform=preflight["platform"],
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
            "approval_source": OPERATOR_ASSISTED_APPROVAL_SOURCE,
            "handoff_public_id": boundary.public_id,
            "confirm_operator_final_click": True,
            "operator_final_click_required": True,
            "automated_submission_authorized": False,
            "queue_submission_authorized": False,
            "global_live_submit_enabled": False,
            "platform_pilot_enabled": False,
            "autopilot_enabled": False,
            "policy_count": preflight["policy_count"],
            "cover_letter_present": preflight["cover_letter_present"],
            "resume_filename": preflight["resume_filename"],
            "unresolved_manual_review_count": preflight["unresolved_manual_review_count"],
            "platform_pilot_setting": policy.pilot_setting_name,
            "platform_display_name": policy.display_name,
            "adapter_version": policy.adapter_version,
            "target_identity_hash": preflight["target_identity_hash"],
            "target_identity": dict(preflight["target_identity"] or {}),
            "target_liveness": dict(preflight.get("target_liveness") or {}),
            "form_schema_hash": preflight.get("form_schema_hash"),
            "form_schema": dict(preflight.get("form_schema") or {}),
        },
    )
    db.add(approval)
    db.flush()
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="operator_assisted_submission_approval_issued",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "approval_reference": approval.reference,
                "handoff_public_id": boundary.public_id,
                "platform": approval.platform,
                "employer": approval.employer,
                "role": approval.role,
                "application_url": approval.application_url,
                "expires_at": approval.expires_at.isoformat(),
                "combined_payload_hash": approval.combined_payload_hash,
                "target_identity_hash": preflight["target_identity_hash"],
                "automated_submission_authorized": False,
            },
        )
    )
    return approval


def _load_owned_operator_approval(
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
        raise OperatorAssistedSubmissionError("Submission approval not found")
    metadata = dict(approval.approval_metadata or {})
    if metadata.get("approval_source") != OPERATOR_ASSISTED_APPROVAL_SOURCE:
        raise OperatorAssistedSubmissionError(
            "Approval was not issued for operator-assisted final click"
        )
    if metadata.get("automated_submission_authorized") is not False:
        raise OperatorAssistedSubmissionError("Operator-assisted approval is not fail-safe")
    if metadata.get("queue_submission_authorized") is not False:
        raise OperatorAssistedSubmissionError("Operator-assisted approval permits queue work")
    return approval


def validate_operator_assisted_approval(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    reference: str,
    consume: bool = False,
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> SubmissionApproval:
    approval = _load_owned_operator_approval(
        db,
        application_id=application.id,
        user_id=user.id,
        reference=reference,
        for_update=consume,
    )
    now = _now()
    if approval.status != SubmissionApprovalStatus.active.value:
        raise OperatorAssistedSubmissionError(
            f"Submission approval is {approval.status}, not active"
        )
    if approval.expires_at <= now:
        approval.status = SubmissionApprovalStatus.expired.value
        raise OperatorAssistedApprovalExpired("Submission approval has expired")

    metadata = dict(approval.approval_metadata or {})
    boundary = _active_final_submit_boundary(
        db,
        application,
        public_id=str(metadata.get("handoff_public_id") or ""),
    )
    if boundary is None:
        raise OperatorAssistedSubmissionError(
            "The exact retained final-submit handoff is no longer active"
        )

    preflight = build_operator_assisted_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )
    if not preflight["ready"]:
        raise OperatorAssistedSubmissionError(
            "Operator-assisted preflight is blocked: " + ", ".join(preflight["blockers"])
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
        field for field, value in expected.items() if getattr(approval, field) != value
    ]
    policy = get_supervised_platform_policy(preflight["platform"])
    if policy and metadata.get("adapter_version") != policy.adapter_version:
        mismatches.append("adapter_version")
    if (
        policy
        and policy.requires_exact_target_identity
        and metadata.get("target_identity_hash") != preflight["target_identity_hash"]
    ):
        mismatches.append("target_identity_hash")
    if metadata.get("form_schema_hash") != preflight.get("form_schema_hash"):
        mismatches.append("form_schema_hash")
    if metadata.get("handoff_public_id") != boundary.public_id:
        mismatches.append("handoff_public_id")
    mismatches = list(dict.fromkeys(mismatches))

    if mismatches:
        approval.status = SubmissionApprovalStatus.revoked.value
        approval.revoked_at = now
        approval.approval_metadata = {
            **metadata,
            "revocation_reason": "approved_payload_changed",
            "mismatched_fields": mismatches,
        }
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="operator_assisted_submission_approval_invalidated",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "approval_reference": approval.reference,
                    "mismatched_fields": mismatches,
                },
            )
        )
        raise OperatorAssistedApprovalMismatch(
            "Approved submission payload changed: " + ", ".join(mismatches)
        )

    if consume:
        if normalize_state(application.automation_state) != ApplicationAutomationState.needs_review.value:
            raise OperatorAssistedSubmissionError(
                "Application must be at the retained final-submit review boundary"
            )
        approval.status = SubmissionApprovalStatus.consumed.value
        approval.consumed_at = now
        attempt_number = int(application.submission_attempt_count or 0) + 1
        approval.approval_metadata = {
            **metadata,
            "consumed_for_attempt": attempt_number,
            "consumed_for_operator_final_click": True,
            "target_liveness_at_consume": dict(preflight.get("target_liveness") or {}),
            "form_schema_at_consume": dict(preflight.get("form_schema") or {}),
        }
        application.submission_attempt_count = attempt_number
        application.last_submission_attempt_at = now
        application.status = ApplicationStatus.applying
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.applying,
            "operator_assisted_final_action_authorized",
            {
                "approval_reference": approval.reference,
                "handoff_public_id": boundary.public_id,
                "attempt": attempt_number,
                "combined_payload_hash": approval.combined_payload_hash,
                "target_identity_hash": preflight["target_identity_hash"],
                "operator_final_click_required": True,
                "worker_task_created": False,
                "queue_created": False,
            },
        )
    return approval


def operator_final_click_authorized(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
) -> bool:
    if session.user_id != user_id:
        return False
    if session.challenge_type != HandoffChallengeType.final_submit.value:
        return False
    approval = (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == session.application_id,
            SubmissionApproval.user_id == user_id,
            SubmissionApproval.status == SubmissionApprovalStatus.consumed.value,
        )
        .order_by(SubmissionApproval.consumed_at.desc(), SubmissionApproval.id.desc())
        .first()
    )
    if not approval:
        return False
    metadata = dict(approval.approval_metadata or {})
    return bool(
        metadata.get("approval_source") == OPERATOR_ASSISTED_APPROVAL_SOURCE
        and metadata.get("handoff_public_id") == session.public_id
        and metadata.get("operator_final_click_required") is True
        and metadata.get("automated_submission_authorized") is False
        and metadata.get("queue_submission_authorized") is False
    )


__all__ = [
    "OPERATOR_ASSISTED_APPROVAL_SOURCE",
    "OperatorAssistedApprovalExpired",
    "OperatorAssistedApprovalMismatch",
    "OperatorAssistedSubmissionError",
    "build_operator_assisted_preflight",
    "get_operator_final_submit_boundary",
    "issue_operator_assisted_approval",
    "operator_final_click_authorized",
    "validate_operator_assisted_approval",
]
