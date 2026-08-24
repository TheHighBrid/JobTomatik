"""Exact-payload approval gate for supervised ATS submissions.

This service never submits an application. It creates short-lived, one-time
approval records bound to an exact employer, role, URL, idempotency key, profile,
resume, cover letter, approved answer-policy payload, and any platform-required
target identity. Any mutation, expiry, open review, unsupported platform, or
feature-flag change invalidates the approval.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import parse_qs, urlsplit

import httpx
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
from app.services.ats_greenhouse import inspect_greenhouse_schema, parse_greenhouse_job_url
from app.services.operations_policy import platform_key_for_url
from app.services.supervised_platforms import (
    GREENHOUSE_PLATFORM_KEY,
    SupervisedPlatformPolicy,
    get_supervised_platform_policy,
)
from app.services.supervised_target_identity import (
    persisted_supervised_target_metadata,
    target_identity_hash,
    target_url_for_job,
)


settings = get_settings()
# Compatibility alias for existing imports. Operational decisions use the registry.
SUPPORTED_PLATFORM = GREENHOUSE_PLATFORM_KEY
MANUAL_GREENHOUSE_PHASE_B_SOURCE = "manual_greenhouse_phase_b"
TARGET_LIVENESS_TIMEOUT_SECONDS = 5.0
FORM_SCHEMA_TIMEOUT_SECONDS = 5.0
FORM_SCHEMA_FINGERPRINT_VERSION = 1


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


def _platform_policy(platform: str) -> Optional[SupervisedPlatformPolicy]:
    return get_supervised_platform_policy(platform)


def _resolved_target_metadata(
    job: Job,
    supplied: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    if supplied is not None:
        return dict(supplied)
    return persisted_supervised_target_metadata(job)


def _greenhouse_job_id(value: str) -> Optional[str]:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return None

    query = parse_qs(parsed.query, keep_blank_values=True)
    for query_key in ("gh_jid", "job_id"):
        for item in query.get(query_key, []):
            candidate = str(item or "").strip()
            if candidate:
                return candidate

    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part.lower() == "jobs" and index + 1 < len(parts):
            candidate = str(parts[index + 1] or "").strip()
            if candidate:
                return candidate
    return None


def _greenhouse_target_liveness(application_url: str) -> Dict[str, Any]:
    """Fail closed when an exact manually selected Greenhouse posting is stale.

    Greenhouse currently redirects closed job URLs back to the company board with
    ``?error=true``. We also treat a changed or missing numeric job identity after
    redirects as closed. Transport failures remain a separate unverified blocker so
    a temporary network problem cannot be misreported as an expired vacancy.
    """

    original_url = str(application_url or "").strip()
    result: Dict[str, Any] = {
        "checked": True,
        "live": False,
        "status_code": None,
        "final_url": None,
        "blocker": "application_target_liveness_unverified",
    }
    if not original_url:
        return result

    try:
        response = _get_greenhouse_target_response(
            original_url,
            follow_redirects=True,
            timeout=TARGET_LIVENESS_TIMEOUT_SECONDS,
            headers={
                "User-Agent": "JobTomatik/1.0 supervised-target-liveness",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
    except (httpx.HTTPError, ValueError):
        return result

    final_url = str(response.url)
    result["status_code"] = int(response.status_code)
    result["final_url"] = final_url

    if response.status_code in {404, 410}:
        result["blocker"] = "application_target_closed_or_expired"
        return result
    if response.status_code >= 400:
        return result

    try:
        final_parts = urlsplit(final_url)
    except ValueError:
        return result
    final_host = (final_parts.hostname or "").lower().rstrip(".")
    if not final_host or not (
        final_host == "greenhouse.io" or final_host.endswith(".greenhouse.io")
    ):
        return result

    final_query = parse_qs(final_parts.query, keep_blank_values=True)
    error_values = {
        str(value or "").strip().lower()
        for value in final_query.get("error", [])
    }
    if error_values.intersection({"1", "true", "yes"}):
        result["blocker"] = "application_target_closed_or_expired"
        return result

    original_job_id = _greenhouse_job_id(original_url)
    final_job_id = _greenhouse_job_id(final_url)
    if original_job_id:
        if final_job_id != original_job_id:
            result["blocker"] = "application_target_closed_or_expired"
            return result
    else:
        final_path = final_parts.path.lower().rstrip("/")
        embedded_token = any(
            str(item or "").strip()
            for item in final_query.get("token", [])
        )
        if not final_job_id and not (
            final_path.endswith("/embed/job_app") and embedded_token
        ):
            return result

    result["live"] = True
    result["blocker"] = None
    return result


def _get_greenhouse_target_response(url: str, **kwargs: Any) -> httpx.Response:
    """HTTP seam for the HTML liveness probe, independent of schema fetching."""

    return httpx.get(url, **kwargs)


def _get_greenhouse_schema_response(url: str, **kwargs: Any) -> httpx.Response:
    """HTTP seam for the Boards API probe, independent of target liveness."""

    return httpx.get(url, **kwargs)


def _canonicalize_form_schema_value(value: Any) -> Any:
    """Normalize public Greenhouse schema data for order-insensitive hashing."""

    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize_form_schema_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        normalized = [_canonicalize_form_schema_value(item) for item in value]
        return sorted(normalized, key=_canonical_json)
    return value


def _greenhouse_schema_fingerprint(schema: Mapping[str, Any], job_id: str) -> str:
    """Hash the live application-question surface, including selectable options."""

    payload = {
        "version": FORM_SCHEMA_FINGERPRINT_VERSION,
        "job_id": str(job_id or "").strip(),
        "questions": _canonicalize_form_schema_value(schema.get("questions") or []),
        "location_questions": _canonicalize_form_schema_value(
            schema.get("location_questions") or []
        ),
        "demographic_questions": _canonicalize_form_schema_value(
            schema.get("demographic_questions") or []
        ),
        "data_compliance": _canonicalize_form_schema_value(
            schema.get("data_compliance") or schema.get("compliance") or []
        ),
    }
    return _hash_value(payload)


def _greenhouse_form_schema_status(application_url: str) -> Dict[str, Any]:
    """Fetch and fingerprint the official live Greenhouse question schema.

    Only public form structure is retained. Answers are never stored here. Unknown
    field types or transport/parsing failures block supervised approval rather than
    allowing a stale dry-run payload to reach the live worker.
    """

    result: Dict[str, Any] = {
        "checked": True,
        "verified": False,
        "status_code": None,
        "board_token": None,
        "job_id": None,
        "schema_hash": None,
        "fingerprint_version": FORM_SCHEMA_FINGERPRINT_VERSION,
        "question_count": None,
        "required_question_count": None,
        "required_uploads": [],
        "unsupported_fields": [],
        "blocker": "application_form_schema_unverified",
    }
    board_token, job_id = parse_greenhouse_job_url(application_url)
    result["board_token"] = board_token
    result["job_id"] = job_id
    if not board_token or not job_id:
        return result

    schema_url = (
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
    )
    try:
        response = _get_greenhouse_schema_response(
            schema_url,
            params={"questions": "true"},
            timeout=FORM_SCHEMA_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={
                "User-Agent": "JobTomatik/1.0 supervised-form-schema",
                "Accept": "application/json",
            },
        )
    except (httpx.HTTPError, ValueError):
        return result

    result["status_code"] = int(response.status_code)
    if response.status_code >= 400:
        return result

    try:
        schema = response.json()
    except (TypeError, ValueError, json.JSONDecodeError):
        return result
    if not isinstance(schema, Mapping):
        return result

    inspection = inspect_greenhouse_schema(dict(schema))
    questions = list(inspection.get("questions") or [])
    unsupported = list(inspection.get("unsupported_fields") or [])
    result["question_count"] = int(inspection.get("question_count") or 0)
    result["required_question_count"] = sum(
        1 for question in questions if question.get("required") is True
    )
    result["required_uploads"] = list(inspection.get("required_uploads") or [])
    result["unsupported_fields"] = unsupported
    # A successful response is not proof that Greenhouse returned a usable form.
    # Require at least one parsed question and a concrete type for every field so
    # empty/malformed payloads cannot be certified merely because no *known*
    # unsupported type happened to be present.
    parsed_question_surface = bool(questions) and all(
        int(question.get("aggregate_field_count") or 0) > 0
        and bool(question.get("field_types"))
        and all(str(field_type or "").strip() for field_type in question["field_types"])
        for question in questions
    )
    if not parsed_question_surface:
        return result
    if not inspection.get("schema_certified") or unsupported:
        result["blocker"] = "application_form_schema_unsupported"
        return result

    result["schema_hash"] = _greenhouse_schema_fingerprint(schema, job_id)
    result["verified"] = True
    result["blocker"] = None
    return result


def _should_probe_target_liveness(job: Job, platform: str) -> bool:
    raw_data = dict(job.raw_data or {})
    return bool(
        settings.is_production
        and platform == GREENHOUSE_PLATFORM_KEY
        and raw_data.get("selection_source") == MANUAL_GREENHOUSE_PHASE_B_SOURCE
    )


def _should_probe_form_schema(job: Job, platform: str) -> bool:
    return _should_probe_target_liveness(job, platform)


def build_submission_snapshot(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    original_target_url = target_url_for_job(job)
    platform = platform_key_for_url(original_target_url)
    policy = _platform_policy(platform)
    identity = _resolved_target_metadata(job, target_metadata)
    identity_hash = (
        target_identity_hash(identity)
        if policy and policy.requires_exact_target_identity
        else None
    )
    application_url = str(
        identity.get("canonical_application_url")
        if identity and identity.get("canonical_application_url")
        else original_target_url
    ).strip()

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
        target_url=application_url,
        company=str(job.company or ""),
    )
    resume_hash = _hash_file(user.resume_path)
    cover_letter_hash = _hash_value(application.cover_letter or "")
    answer_payload_hash = _hash_value(policies)
    profile_snapshot_hash = _hash_value(profile_payload)

    combined_payload: Dict[str, Any] = {
        "application_id": application.id,
        "user_id": user.id,
        "job_id": job.id,
        "employer": str(job.company or "").strip(),
        "role": str(job.title or "").strip(),
        "application_url": application_url,
        "platform": platform,
        "submission_idempotency_key": application.submission_idempotency_key,
        "profile_snapshot_hash": profile_snapshot_hash,
        "resume_hash": resume_hash,
        "cover_letter_hash": cover_letter_hash,
        "answer_payload_hash": answer_payload_hash,
    }
    # Preserve existing Greenhouse hashes. Exact target identity is added only for
    # platforms whose policy explicitly requires it.
    if policy and policy.requires_exact_target_identity:
        combined_payload["target_identity_hash"] = identity_hash
    combined_payload_hash = _hash_value(combined_payload)

    return {
        "application_id": application.id,
        "user_id": user.id,
        "job_id": job.id,
        "employer": str(job.company or "").strip(),
        "role": str(job.title or "").strip(),
        "application_url": application_url,
        "original_application_url": original_target_url,
        "platform": platform,
        "platform_display_name": policy.display_name if policy else platform,
        "adapter_version": policy.adapter_version if policy else None,
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
        "target_identity": identity,
        "target_identity_hash": identity_hash,
        "target_identity_verified": bool(identity.get("verified")) if identity else False,
    }


def build_supervised_preflight(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    snapshot = build_submission_snapshot(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )
    state = application.automation_state or ApplicationAutomationState.preparing.value
    open_reviews = _active_review_count(db, application.id)
    live_enabled = bool(settings.allow_real_application_submit)
    policy = _platform_policy(snapshot["platform"])
    pilot_enabled = policy.pilot_enabled(settings) if policy else False
    target_liveness: Dict[str, Any] = {
        "checked": False,
        "live": None,
        "status_code": None,
        "final_url": None,
        "blocker": None,
    }
    form_schema: Dict[str, Any] = {
        "checked": False,
        "verified": None,
        "status_code": None,
        "board_token": None,
        "job_id": None,
        "schema_hash": None,
        "fingerprint_version": FORM_SCHEMA_FINGERPRINT_VERSION,
        "question_count": None,
        "required_question_count": None,
        "required_uploads": [],
        "unsupported_fields": [],
        "blocker": None,
    }

    blockers: list[str] = []
    if not live_enabled:
        blockers.append("global_live_submit_disabled")
    if policy is None:
        blockers.append("unsupported_platform")
    elif not pilot_enabled:
        blockers.append(policy.pilot_disabled_blocker)
    if policy and policy.requires_exact_target_identity:
        identity_blockers = snapshot["target_identity"].get("blockers") or []
        blockers.extend(str(item) for item in identity_blockers if str(item))
        if not snapshot["target_identity_verified"] and not identity_blockers:
            blockers.append("exact_target_identity_unverified")
        if not snapshot["target_identity_hash"]:
            blockers.append("exact_target_identity_hash_missing")
    if _should_probe_target_liveness(job, snapshot["platform"]):
        target_liveness = _greenhouse_target_liveness(snapshot["application_url"])
        liveness_blocker = str(target_liveness.get("blocker") or "").strip()
        if liveness_blocker:
            blockers.append(liveness_blocker)
    if _should_probe_form_schema(job, snapshot["platform"]):
        form_schema = _greenhouse_form_schema_status(snapshot["application_url"])
        schema_blocker = str(form_schema.get("blocker") or "").strip()
        if schema_blocker:
            blockers.append(schema_blocker)
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

    combined_payload_hash = snapshot["combined_payload_hash"]
    form_schema_hash = str(form_schema.get("schema_hash") or "").strip() or None
    if form_schema_hash:
        combined_payload_hash = _hash_value({
            "base_combined_payload_hash": combined_payload_hash,
            "form_schema_fingerprint_version": form_schema.get("fingerprint_version"),
            "form_schema_hash": form_schema_hash,
        })

    blockers = list(dict.fromkeys(blockers))
    return {
        "ready": not blockers,
        "blockers": blockers,
        "application_id": application.id,
        "platform": snapshot["platform"],
        "platform_display_name": snapshot["platform_display_name"],
        "adapter_version": snapshot["adapter_version"],
        "employer": snapshot["employer"],
        "role": snapshot["role"],
        "application_url": snapshot["application_url"],
        "original_application_url": snapshot["original_application_url"],
        "automation_state": state,
        "unresolved_manual_review_count": open_reviews,
        "global_live_submit_enabled": live_enabled,
        "platform_pilot_enabled": pilot_enabled,
        "submission_idempotency_key": snapshot["submission_idempotency_key"],
        "profile_snapshot_hash": snapshot["profile_snapshot_hash"],
        "resume_hash": snapshot["resume_hash"],
        "cover_letter_hash": snapshot["cover_letter_hash"],
        "answer_payload_hash": snapshot["answer_payload_hash"],
        "combined_payload_hash": combined_payload_hash,
        "policy_count": snapshot["policy_count"],
        "cover_letter_present": snapshot["cover_letter_present"],
        "resume_filename": snapshot["resume_filename"],
        "target_identity": snapshot["target_identity"],
        "target_identity_hash": snapshot["target_identity_hash"],
        "target_identity_verified": snapshot["target_identity_verified"],
        "target_liveness": target_liveness,
        "form_schema_hash": form_schema_hash,
        "form_schema": form_schema,
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
    target_metadata: Optional[Mapping[str, Any]] = None,
) -> SubmissionApproval:
    preflight = build_supervised_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )
    if not preflight["ready"]:
        raise SupervisedSubmissionApprovalError(
            "Supervised submission preflight is blocked: "
            + ", ".join(preflight["blockers"])
        )
    policy = _platform_policy(preflight["platform"])
    if policy is None:
        raise SupervisedSubmissionApprovalError("Unsupported supervised platform")
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
        field
        for field, (provided, expected) in confirmations.items()
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
            "approval_source": "authenticated_user_api",
            "confirm_final_submit": True,
            "policy_count": preflight["policy_count"],
            "cover_letter_present": preflight["cover_letter_present"],
            "resume_filename": preflight["resume_filename"],
            "unresolved_manual_review_count": 0,
            "global_live_submit_enabled": True,
            "platform_pilot_enabled": True,
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
                "target_identity_hash": preflight["target_identity_hash"],
                "target_liveness": dict(preflight.get("target_liveness") or {}),
                "form_schema_hash": preflight.get("form_schema_hash"),
            },
        )
    )
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
    target_metadata: Optional[Mapping[str, Any]] = None,
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

    preflight = build_supervised_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )
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
        field
        for field, value in expected.items()
        if getattr(approval, field) != value
    ]
    approval_metadata = dict(approval.approval_metadata or {})
    policy = _platform_policy(preflight["platform"])
    if policy and approval_metadata.get("adapter_version") != policy.adapter_version:
        mismatches.append("adapter_version")
    if (
        policy
        and policy.requires_exact_target_identity
        and approval_metadata.get("target_identity_hash")
        != preflight["target_identity_hash"]
    ):
        mismatches.append("target_identity_hash")
    if approval_metadata.get("form_schema_hash") != preflight.get("form_schema_hash"):
        mismatches.append("form_schema_hash")
    mismatches = list(dict.fromkeys(mismatches))

    if mismatches:
        approval.status = SubmissionApprovalStatus.revoked.value
        approval.revoked_at = now
        approval.approval_metadata = {
            **approval_metadata,
            "revocation_reason": "approved_payload_changed",
            "mismatched_fields": mismatches,
        }
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="supervised_submission_approval_invalidated",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "approval_reference": approval.reference,
                    "mismatched_fields": mismatches,
                },
            )
        )
        raise SupervisedSubmissionApprovalMismatch(
            "Approved submission payload changed: " + ", ".join(mismatches)
        )

    if consume:
        approval.status = SubmissionApprovalStatus.consumed.value
        approval.consumed_at = now
        approval.approval_metadata = {
            **approval_metadata,
            "consumed_for_attempt": (application.submission_attempt_count or 0) + 1,
            "target_liveness_at_consume": dict(
                preflight.get("target_liveness") or {}
            ),
            "form_schema_at_consume": dict(preflight.get("form_schema") or {}),
        }
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="supervised_submission_approval_consumed",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "approval_reference": approval.reference,
                    "attempt": (application.submission_attempt_count or 0) + 1,
                    "combined_payload_hash": approval.combined_payload_hash,
                    "target_identity_hash": preflight["target_identity_hash"],
                    "target_liveness": dict(preflight.get("target_liveness") or {}),
                    "form_schema_hash": preflight.get("form_schema_hash"),
                },
            )
        )
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
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="supervised_submission_approval_revoked",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "approval_reference": approval.reference,
                    "reason": reason,
                },
            )
        )
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
