"""Human-final-click bridge for supervised Phase B submissions.

This lane deliberately does not authorize JobTomatik to click the final submit
control, publish Celery work, or enable a live-submit feature flag. It preserves the
existing exact-target/payload approval and evidence-review chain while requiring the
owner to perform the consequential final click directly in the employer form.
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
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.application_state import (
    normalize_state,
    record_submission_evidence,
    transition_application_state,
)
from app.services.submission_evidence_review import STRONG_EVIDENCE_TYPES
from app.services.supervised_platforms import get_supervised_platform_policy
from app.services.supervised_submission import build_supervised_preflight


settings = get_settings()
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


def build_operator_assisted_preflight(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Reuse every structural supervised check while requiring automation to stay off."""

    base = build_supervised_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )
    policy = get_supervised_platform_policy(base.get("platform"))
    ignored = _operator_execution_blockers(base)
    blockers = [
        str(item)
        for item in base.get("blockers") or []
        if str(item) not in ignored
    ]

    # This lane exists specifically so a human can perform the final action while
    # JobTomatik remains fail-safe. If automation authority is unexpectedly enabled,
    # refuse to create a second overlapping path.
    if base.get("global_live_submit_enabled") is not False:
        blockers.append("operator_assisted_requires_global_submit_disabled")
    if policy is None:
        # unsupported_platform is already retained from the base preflight.
        pass
    elif base.get("platform_pilot_enabled") is not False:
        blockers.append("operator_assisted_requires_platform_pilot_disabled")
    if bool(getattr(settings, "autopilot_enabled", False)):
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
        "autopilot_enabled": bool(getattr(settings, "autopilot_enabled", False)),
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


def issue_operator_assisted_approval(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    confirm_employer: str,
    confirm_role: str,
    confirm_application_url: str,
    confirm_operator_final_click: bool,
    expires_in_minutes: Optional[int] = None,
    notes: Optional[str] = None,
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> SubmissionApproval:
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
            "unresolved_manual_review_count": 0,
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
    metadata = dict(approval.approval_metadata or {})
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
        if normalize_state(application.automation_state) != ApplicationAutomationState.ready_to_apply.value:
            raise OperatorAssistedSubmissionError(
                "Application must be ready_to_apply before operator final-action authorization"
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
                "attempt": attempt_number,
                "combined_payload_hash": approval.combined_payload_hash,
                "target_identity_hash": preflight["target_identity_hash"],
                "operator_final_click_required": True,
                "worker_task_created": False,
                "queue_created": False,
            },
        )
    return approval


def record_operator_confirmation(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    reference: str,
    evidence_type: str,
    final_url: str,
    confirmation_text: Optional[str] = None,
    external_application_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> SubmissionEvidence:
    approval = _load_owned_operator_approval(
        db,
        application_id=application.id,
        user_id=user.id,
        reference=reference,
        for_update=True,
    )
    if approval.status != SubmissionApprovalStatus.consumed.value:
        raise OperatorAssistedSubmissionError(
            "Operator-assisted approval must be consumed before confirmation evidence is recorded"
        )
    state = normalize_state(application.automation_state)
    if state not in {
        ApplicationAutomationState.applying.value,
        ApplicationAutomationState.submission_uncertain.value,
    }:
        raise OperatorAssistedSubmissionError(
            "Application is not waiting for operator-assisted confirmation evidence"
        )

    normalized_type = str(evidence_type or "").strip()
    if normalized_type not in STRONG_EVIDENCE_TYPES:
        raise OperatorAssistedSubmissionError(
            "Operator-assisted confirmation requires a strong evidence type"
        )
    if not str(final_url or "").strip():
        raise OperatorAssistedSubmissionError("final_url is required")
    if not (
        str(confirmation_text or "").strip()
        or str(external_application_id or "").strip()
    ):
        raise OperatorAssistedSubmissionError(
            "Concrete confirmation text or an external application id is required"
        )

    evidence = record_submission_evidence(
        db,
        application,
        normalized_type,
        is_sufficient=True,
        final_url=str(final_url).strip(),
        confirmation_text=str(confirmation_text or "").strip() or None,
        external_application_id=str(external_application_id or "").strip() or None,
        payload_hash=approval.combined_payload_hash,
        metadata={
            "capture_source": "authenticated_user_operator_assisted",
            "operator_final_click_reported": True,
            "approval_reference": approval.reference,
            "combined_payload_hash": approval.combined_payload_hash,
            "notes": str(notes or "").strip() or None,
        },
    )
    db.flush()

    if state == ApplicationAutomationState.submission_uncertain.value:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.submitted,
            "operator_assisted_submission_evidence_recorded",
            {
                "approval_reference": approval.reference,
                "evidence_id": evidence.id,
                "evidence_type": evidence.evidence_type,
            },
        )
    else:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.submitted,
            "operator_assisted_submission_evidence_recorded",
            {
                "approval_reference": approval.reference,
                "evidence_id": evidence.id,
                "evidence_type": evidence.evidence_type,
            },
        )
    application.status = ApplicationStatus.applied
    application.applied_at = application.applied_at or _now()
    return evidence


__all__ = [
    "OPERATOR_ASSISTED_APPROVAL_SOURCE",
    "OperatorAssistedApprovalExpired",
    "OperatorAssistedApprovalMismatch",
    "OperatorAssistedSubmissionError",
    "build_operator_assisted_preflight",
    "issue_operator_assisted_approval",
    "record_operator_confirmation",
    "validate_operator_assisted_approval",
]
