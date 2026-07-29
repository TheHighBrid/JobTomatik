"""Fail-closed runtime switches and retained-browser target binding.

This module centralizes the Day 6 operational boundary. It does not promote any
adapter or enable live submission. It answers one question before browser work:
"is this exact execution still authorized for this exact posting?"
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from app.config import get_settings
from app.models.application import Application, ManualReviewReason, ManualReviewTask
from app.models.job import Job
from app.services.operations_policy import (
    AutomationDecision,
    evaluate_circuit_breaker_policy,
    evaluate_platform_policy,
    platform_key_for_url,
)
from app.services.operations_settings import get_operations_settings
from app.services.submission_integrity import canonicalize_submission_url


@dataclass(frozen=True)
class HandoffReasonPolicy:
    reason_code: str
    disposition: str
    resumable: bool
    operator_reason_code: str
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "disposition": self.disposition,
            "resumable": self.resumable,
            "operator_reason_code": self.operator_reason_code,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class HandoffBindingDecision:
    allowed: bool
    code: str
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


_RESUMABLE_BROWSER_REASONS = {
    ManualReviewReason.captcha_detected.value: "captcha_handoff",
    ManualReviewReason.mfa_required.value: "mfa_handoff",
    ManualReviewReason.login_required.value: "login_handoff",
    ManualReviewReason.anti_bot_challenge.value: "anti_bot_handoff",
    ManualReviewReason.application_target_required.value: "navigation_handoff",
}
_MANUAL_ONLY_REASONS = {
    ManualReviewReason.assessment_required.value: "assessment_requires_user",
    ManualReviewReason.legal_answer_missing.value: "legal_answer_requires_user",
    ManualReviewReason.sensitive_answer_missing.value: "sensitive_answer_requires_user",
    ManualReviewReason.ambiguous_question.value: "ambiguous_control_requires_user",
    ManualReviewReason.unsupported_control.value: "unsupported_control_requires_user",
}
_EVIDENCE_REVIEW_REASONS = {
    ManualReviewReason.submission_confirmation_uncertain.value: "confirmation_requires_evidence_review",
}


class OperationalSafetyViolation(ValueError):
    def __init__(self, code: str, message: str, *, metadata: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.metadata = dict(metadata or {})


def _hash_payload(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def classify_handoff_reason(reason_code: Any) -> HandoffReasonPolicy:
    value = str(getattr(reason_code, "value", reason_code) or "")
    if value in _RESUMABLE_BROWSER_REASONS:
        return HandoffReasonPolicy(
            reason_code=value,
            disposition="resumable_browser",
            resumable=True,
            operator_reason_code=_RESUMABLE_BROWSER_REASONS[value],
            explanation="A retained browser may resume only after the authenticated user clears the challenge.",
        )
    if value in _MANUAL_ONLY_REASONS:
        return HandoffReasonPolicy(
            reason_code=value,
            disposition="manual_only",
            resumable=False,
            operator_reason_code=_MANUAL_ONLY_REASONS[value],
            explanation="This boundary requires an explicit user decision and cannot be auto-resumed.",
        )
    if value in _EVIDENCE_REVIEW_REASONS:
        return HandoffReasonPolicy(
            reason_code=value,
            disposition="evidence_review",
            resumable=False,
            operator_reason_code=_EVIDENCE_REVIEW_REASONS[value],
            explanation="The system must review independent confirmation evidence before any terminal state.",
        )
    return HandoffReasonPolicy(
        reason_code=value,
        disposition="non_resumable",
        resumable=False,
        operator_reason_code="handoff_not_certified",
        explanation="No certified retained-browser resume policy exists for this review reason.",
    )


def _job_target_url(application: Application, job: Job) -> str:
    raw = dict(job.raw_data or {})
    return str(
        application.application_target_url
        or raw.get("selected_apply_url")
        or job.url
        or ""
    ).strip()


def _posting_identity(url: str) -> str:
    canonical = canonicalize_submission_url(url)
    if not canonical:
        return ""
    parsed = urlparse(canonical)
    platform = platform_key_for_url(canonical)
    parts = [part for part in (parsed.path or "").split("/") if part]

    token = ""
    if platform == "greenhouse":
        for index, part in enumerate(parts):
            if part.lower() in {"jobs", "job"} and index + 1 < len(parts):
                token = parts[index + 1]
        token = token or (parts[-1] if parts else "")
    elif platform in {"lever", "ashby", "smartrecruiters"}:
        token = parts[-1] if parts else ""
    elif platform == "workday":
        # Workday URLs frequently end with the requisition token after /job/.
        for index, part in enumerate(parts):
            if part.lower() == "job" and index + 1 < len(parts):
                token = parts[-1]
        token = token or (parts[-1] if parts else "")
    else:
        token = canonical

    normalized_token = re.sub(r"[^a-z0-9._-]+", "", token.lower())
    return f"{platform}:{(parsed.hostname or '').lower()}:{normalized_token}"


def build_handoff_target_binding(
    application: Application,
    job: Job,
    review: ManualReviewTask,
    *,
    current_url: Optional[str] = None,
    current_fingerprint: Optional[str] = None,
    target_resolution_only: bool = False,
) -> Dict[str, Any]:
    expected_url = canonicalize_submission_url(current_url or _job_target_url(application, job))
    platform = platform_key_for_url(expected_url)
    posting_identity = _posting_identity(expected_url)
    binding = {
        "version": 1,
        "application_id": application.id,
        "manual_review_id": review.id,
        "user_id": application.user_id,
        "job_id": application.job_id,
        "platform": platform,
        "expected_url": expected_url,
        "posting_identity": posting_identity,
        "target_resolution_only": bool(target_resolution_only),
        "initial_fingerprint": str(current_fingerprint or ""),
    }
    binding["binding_hash"] = _hash_payload(binding)
    return binding


def validate_handoff_target_binding(
    session,
    application: Application,
    job: Job,
    review: ManualReviewTask,
    *,
    current_url: Optional[str] = None,
) -> HandoffBindingDecision:
    metadata = dict(session.handoff_metadata or {})
    binding = dict(metadata.get("target_binding") or {})
    if not binding:
        return HandoffBindingDecision(
            False,
            "handoff_binding_missing",
            "The retained handoff has no certified target binding.",
            {"operator_reason_code": "handoff_binding_missing"},
        )

    identity_fields = {
        "application_id": application.id,
        "manual_review_id": review.id,
        "user_id": application.user_id,
        "job_id": application.job_id,
    }
    mismatches = {
        key: {"expected": binding.get(key), "actual": actual}
        for key, actual in identity_fields.items()
        if binding.get(key) != actual
    }
    if mismatches:
        return HandoffBindingDecision(
            False,
            "handoff_record_identity_mismatch",
            "The retained handoff no longer belongs to the same application records.",
            {
                "mismatches": mismatches,
                "operator_reason_code": "wrong_application_resume",
            },
        )

    target_resolution_only = bool(binding.get("target_resolution_only"))
    active_url = canonicalize_submission_url(current_url or session.current_url or "")
    if not active_url:
        return HandoffBindingDecision(
            False,
            "handoff_current_url_missing",
            "The retained browser did not provide a current URL for target verification.",
            {"operator_reason_code": "handoff_target_unverifiable"},
        )

    actual_platform = platform_key_for_url(active_url)
    expected_platform = str(binding.get("platform") or "")
    if not target_resolution_only and expected_platform != actual_platform:
        return HandoffBindingDecision(
            False,
            "handoff_platform_mismatch",
            "The retained browser is no longer on the approved ATS platform.",
            {
                "expected_platform": expected_platform,
                "actual_platform": actual_platform,
                "operator_reason_code": "wrong_platform_resume",
            },
        )

    expected_posting = str(binding.get("posting_identity") or "")
    actual_posting = _posting_identity(active_url)
    if not target_resolution_only and expected_posting and actual_posting != expected_posting:
        return HandoffBindingDecision(
            False,
            "handoff_posting_mismatch",
            "The retained browser is on a different posting than the approved handoff.",
            {
                "expected_posting_identity": expected_posting,
                "actual_posting_identity": actual_posting,
                "operator_reason_code": "wrong_posting_resume",
            },
        )

    return HandoffBindingDecision(
        True,
        "handoff_binding_verified",
        "The retained browser is bound to the approved application and posting.",
        {
            "platform": actual_platform,
            "posting_identity": actual_posting,
            "target_resolution_only": target_resolution_only,
        },
    )


def require_handoff_target_binding(
    session,
    application: Application,
    job: Job,
    review: ManualReviewTask,
    *,
    current_url: Optional[str] = None,
) -> HandoffBindingDecision:
    decision = validate_handoff_target_binding(
        session,
        application,
        job,
        review,
        current_url=current_url,
    )
    if not decision.allowed:
        raise OperationalSafetyViolation(decision.code, decision.reason, metadata=decision.metadata)
    return decision


def evaluate_execution_safety(
    db,
    user,
    *,
    url: str,
    dry_run: bool,
    requires_handoff: bool = False,
    autopilot: bool = False,
    now: Optional[datetime] = None,
) -> AutomationDecision:
    operations = get_operations_settings()
    core = get_settings()

    platform_decision = evaluate_platform_policy(url)
    if not platform_decision.allowed:
        return platform_decision

    if autopilot and not operations.autopilot_enabled:
        return AutomationDecision(
            False,
            "global_autopilot_disabled",
            "Autonomous scheduling is not enabled in the current operations profile.",
            {"operator_reason_code": "autopilot_kill_switch"},
        )

    if not dry_run and not core.allow_real_application_submit:
        return AutomationDecision(
            False,
            "real_submission_disabled",
            "Live submission is disabled by the global real-submit gate.",
            {"operator_reason_code": "real_submit_kill_switch"},
        )

    # Dry-run handoffs remain available for certification. Live retained sessions
    # require the explicit handoff flag in addition to the real-submit gate.
    if requires_handoff and not dry_run and not core.enable_resumable_handoffs:
        return AutomationDecision(
            False,
            "resumable_handoffs_disabled",
            "Live retained-browser handoffs are disabled in the current profile.",
            {"operator_reason_code": "handoff_kill_switch"},
        )

    breaker = evaluate_circuit_breaker_policy(db, user.id, url=url, now=now)
    if not breaker.allowed:
        return breaker

    return AutomationDecision(
        True,
        "execution_safety_allowed",
        "All runtime switches and circuit breakers permit this bounded execution.",
        {
            "platform": platform_key_for_url(url),
            "dry_run": bool(dry_run),
            "requires_handoff": bool(requires_handoff),
            "autopilot": bool(autopilot),
        },
    )


def operational_safety_manifest() -> Dict[str, Any]:
    policies = {}
    for reason in ManualReviewReason:
        policies[reason.value] = classify_handoff_reason(reason).to_dict()
    return {
        "version": "1.0.0",
        "switch_order": [
            "global_kill_switch",
            "autopilot",
            "platform",
            "real_submit",
            "resumable_handoff",
            "circuit_breaker",
            "target_binding",
        ],
        "handoff_reason_policies": policies,
        "invariants": {
            "captcha_mfa_login_anti_bot_are_user_cleared_only": True,
            "assessments_and_legal_answers_are_never_auto_resumed": True,
            "ambiguous_controls_are_never_guessed": True,
            "uncertain_confirmation_requires_evidence_review": True,
            "wrong_application_or_posting_resume_is_blocked": True,
            "clustered_failures_trip_user_or_platform_breakers": True,
        },
    }
