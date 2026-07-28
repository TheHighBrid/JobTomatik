from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationEvent, SubmissionEvidence
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import (
    ACTIVE_SUBMISSION_ATTEMPT_STATUSES,
    SubmissionAttempt,
    SubmissionAttemptStatus,
    SubmissionEvidenceReceipt,
    SubmissionIdentityAlias,
)
from app.services.operations_policy import platform_key_for_url
from app.services.supervised_target_identity import persisted_supervised_target_metadata


_TRACKING_QUERY_KEYS = {
    "source",
    "ref",
    "referrer",
    "tracking",
    "trackingid",
    "gh_src",
    "lever-source",
}
_LISTING_HOSTS = {
    "www.linkedin.com",
    "linkedin.com",
    "jobbank.gc.ca",
    "www.jobbank.gc.ca",
    "guichetemplois.gc.ca",
    "www.guichetemplois.gc.ca",
}
_LISTING_PATH_MARKERS = (
    "/jobs/view/",
    "/jobs/collections/",
    "/jobsearch/jobposting/",
    "/rechercheemplois/offredemploi/",
)


class DuplicateSubmissionIdentityError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        existing_application_id: Optional[int] = None,
        alias_type: Optional[str] = None,
        alias_key: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.existing_application_id = existing_application_id
        self.alias_type = alias_type
        self.alias_key = alias_key


class SubmissionAttemptReservationError(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_text(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower())).strip()


def canonicalize_submission_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = host
    if port and not ((parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
            continue
        query.append((key, item))
    query.sort()
    return urlunparse((parsed.scheme.lower(), netloc, path, "", urlencode(query), ""))


def _is_source_listing(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return host in _LISTING_HOSTS and any(marker in (parsed.path or "") for marker in _LISTING_PATH_MARKERS)


def _alias(alias_type: str, canonical_value: str, metadata: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    value = str(canonical_value or "").strip()
    return {
        "alias_type": alias_type,
        "canonical_value": value,
        "alias_key": _hash_value({"type": alias_type, "value": value}),
        "alias_metadata": dict(metadata or {}),
    }


def build_submission_identity_aliases(
    job: Job,
    *,
    application: Optional[Application] = None,
    target_metadata: Optional[Mapping[str, Any]] = None,
    final_url: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Build strong and contextual posting aliases without guessing identity.

    Verified ATS posting IDs survive URL redirects. Generic URLs are combined with
    employer and role so a reusable URL hosting a different posting does not collide.
    """

    raw = dict(job.raw_data or {})
    metadata = dict(target_metadata or persisted_supervised_target_metadata(job) or {})
    company = _normalized_text(job.company)
    role = _normalized_text(job.title)
    source = str(getattr(job.source, "value", job.source) or "manual").lower()
    aliases: list[Dict[str, Any]] = []

    def add(item: Dict[str, Any]) -> None:
        if not item["canonical_value"]:
            return
        if not any(existing["alias_key"] == item["alias_key"] for existing in aliases):
            aliases.append(item)

    platform = str(metadata.get("platform") or "").strip().lower()
    site = str(metadata.get("site") or "").strip().lower()
    posting_id = str(metadata.get("posting_id") or "").strip()
    region = str(metadata.get("region") or "").strip().lower()
    if platform and posting_id:
        add(_alias(
            "verified_platform_posting",
            "|".join([platform, region, site, posting_id]),
            {
                "platform": platform,
                "site": site,
                "posting_id": posting_id,
                "region": region,
                "target_identity_hash": metadata.get("identity_hash"),
            },
        ))

    external_id = str(job.external_id or "").strip()
    if external_id:
        add(_alias("source_external_id", f"{source}|{external_id}"))

    source_url = canonicalize_submission_url(
        (application.source_listing_url if application else None) or job.url
    )
    if source_url and _is_source_listing(source_url):
        add(_alias("source_listing_url", source_url, {"source": source}))

    target_urls = [
        application.application_target_url if application else None,
        raw.get("selected_apply_url"),
        metadata.get("canonical_application_url"),
        final_url,
    ]
    if job.url and not _is_source_listing(str(job.url)):
        target_urls.append(job.url)
    for candidate in target_urls:
        canonical = canonicalize_submission_url(candidate)
        if not canonical or _is_source_listing(canonical):
            continue
        candidate_platform = platform_key_for_url(canonical)
        add(_alias(
            "contextual_application_target",
            "|".join([candidate_platform, canonical, company, role]),
            {
                "platform": candidate_platform,
                "canonical_url": canonical,
                "company": company,
                "role": role,
            },
        ))

    return aliases


def find_submission_identity_conflict(
    db: Session,
    user_id: int,
    aliases: Sequence[Mapping[str, Any]],
    *,
    current_application_id: Optional[int] = None,
) -> Optional[SubmissionIdentityAlias]:
    keys = [str(item.get("alias_key") or "") for item in aliases if item.get("alias_key")]
    if not keys:
        return None
    query = db.query(SubmissionIdentityAlias).filter(
        SubmissionIdentityAlias.user_id == user_id,
        SubmissionIdentityAlias.alias_key.in_(keys),
    )
    if current_application_id is not None:
        query = query.filter(SubmissionIdentityAlias.application_id != current_application_id)
    return query.order_by(SubmissionIdentityAlias.id.asc()).first()


def find_existing_application_for_aliases(
    db: Session,
    user_id: int,
    aliases: Sequence[Mapping[str, Any]],
) -> Optional[Application]:
    conflict = find_submission_identity_conflict(db, user_id, aliases)
    if not conflict:
        return None
    return db.query(Application).filter(Application.id == conflict.application_id).first()


def claim_submission_identity_aliases(
    db: Session,
    application: Application,
    aliases: Sequence[Mapping[str, Any]],
) -> list[SubmissionIdentityAlias]:
    conflict = find_submission_identity_conflict(
        db,
        application.user_id,
        aliases,
        current_application_id=application.id,
    )
    if conflict:
        raise DuplicateSubmissionIdentityError(
            "Another application already owns this posting identity.",
            existing_application_id=conflict.application_id,
            alias_type=conflict.alias_type,
            alias_key=conflict.alias_key,
        )

    existing_keys = {
        row[0]
        for row in db.query(SubmissionIdentityAlias.alias_key)
        .filter(SubmissionIdentityAlias.application_id == application.id)
        .all()
    }
    created: list[SubmissionIdentityAlias] = []
    for item in aliases:
        alias_key = str(item.get("alias_key") or "")
        if not alias_key or alias_key in existing_keys:
            continue
        record = SubmissionIdentityAlias(
            user_id=application.user_id,
            application_id=application.id,
            alias_type=str(item.get("alias_type") or "unknown"),
            alias_key=alias_key,
            canonical_value=str(item.get("canonical_value") or ""),
            alias_metadata=dict(item.get("alias_metadata") or {}),
        )
        db.add(record)
        created.append(record)
        existing_keys.add(alias_key)
    db.flush()
    return created


def application_identity_digest(db: Session, application: Application) -> str:
    keys = sorted(
        row[0]
        for row in db.query(SubmissionIdentityAlias.alias_key)
        .filter(SubmissionIdentityAlias.application_id == application.id)
        .all()
    )
    return _hash_value({
        "user_id": application.user_id,
        "application_id": application.id,
        "aliases": keys,
        "fallback_idempotency_key": application.submission_idempotency_key,
    })


def build_application_idempotency_key(
    user_id: int,
    aliases: Sequence[Mapping[str, Any]],
    *,
    fallback_job_id: int,
) -> str:
    keys = sorted(str(item.get("alias_key") or "") for item in aliases if item.get("alias_key"))
    digest = _hash_value({
        "user_id": user_id,
        "identity_aliases": keys,
        "fallback_job_id": fallback_job_id if not keys else None,
    })
    return f"submission-identity:{digest}"


def evidence_fingerprint(
    application: Application,
    *,
    evidence_type: str,
    final_url: Optional[str],
    confirmation_text: Optional[str],
    external_application_id: Optional[str],
    payload_hash: Optional[str],
    metadata: Optional[Mapping[str, Any]],
) -> str:
    values = dict(metadata or {})
    platform = str(values.get("platform") or values.get("expected_platform") or "").lower()
    strong_receipt = (
        str(external_application_id or "").strip()
        or str(payload_hash or "").strip()
        or _hash_value({
            "confirmation_text": str(confirmation_text or "").strip(),
            "final_url": canonicalize_submission_url(final_url),
        })
    )
    return _hash_value({
        "user_id": application.user_id,
        "platform": platform,
        "evidence_type": evidence_type,
        "receipt": strong_receipt,
    })


def prepare_submission_evidence_receipt(
    db: Session,
    application: Application,
    *,
    evidence_type: str,
    final_url: Optional[str],
    confirmation_text: Optional[str],
    external_application_id: Optional[str],
    payload_hash: Optional[str],
    metadata: Optional[Mapping[str, Any]],
) -> tuple[str, Optional[SubmissionEvidence]]:
    fingerprint = evidence_fingerprint(
        application,
        evidence_type=evidence_type,
        final_url=final_url,
        confirmation_text=confirmation_text,
        external_application_id=external_application_id,
        payload_hash=payload_hash,
        metadata=metadata,
    )
    receipt = (
        db.query(SubmissionEvidenceReceipt)
        .filter(SubmissionEvidenceReceipt.fingerprint == fingerprint)
        .first()
    )
    if not receipt:
        return fingerprint, None
    if receipt.application_id != application.id:
        raise DuplicateSubmissionIdentityError(
            "Confirmation evidence was already attached to another application.",
            existing_application_id=receipt.application_id,
            alias_type="confirmation_evidence",
            alias_key=fingerprint,
        )
    evidence = None
    if receipt.evidence_id:
        evidence = db.query(SubmissionEvidence).filter(
            SubmissionEvidence.id == receipt.evidence_id
        ).first()
    return fingerprint, evidence


def register_submission_evidence_receipt(
    db: Session,
    application: Application,
    evidence: SubmissionEvidence,
    *,
    fingerprint: str,
    evidence_type: str,
    final_url: Optional[str],
    external_application_id: Optional[str],
    payload_hash: Optional[str],
    metadata: Optional[Mapping[str, Any]],
) -> SubmissionEvidenceReceipt:
    receipt = SubmissionEvidenceReceipt(
        fingerprint=fingerprint,
        application_id=application.id,
        user_id=application.user_id,
        evidence_id=evidence.id,
        evidence_type=evidence_type,
        external_application_id=external_application_id,
        payload_hash=payload_hash,
        final_url=canonicalize_submission_url(final_url),
        receipt_metadata=dict(metadata or {}),
    )
    db.add(receipt)
    db.flush()
    return receipt


def approval_submission_binding_hash(approval: SubmissionApproval) -> str:
    metadata = dict(approval.approval_metadata or {})
    return _hash_value({
        "approval_reference": approval.reference,
        "application_id": approval.application_id,
        "user_id": approval.user_id,
        "platform": approval.platform,
        "employer": approval.employer,
        "role": approval.role,
        "application_url": canonicalize_submission_url(approval.application_url),
        "submission_idempotency_key": approval.submission_idempotency_key,
        "profile_snapshot_hash": approval.profile_snapshot_hash,
        "resume_hash": approval.resume_hash,
        "cover_letter_hash": approval.cover_letter_hash,
        "answer_payload_hash": approval.answer_payload_hash,
        "combined_payload_hash": approval.combined_payload_hash,
        "adapter_version": metadata.get("adapter_version"),
        "target_identity_hash": metadata.get("target_identity_hash"),
        "approved_at": approval.approved_at,
        "expires_at": approval.expires_at,
    })


def active_submission_attempt(
    db: Session,
    application_id: int,
) -> Optional[SubmissionAttempt]:
    return (
        db.query(SubmissionAttempt)
        .filter(
            SubmissionAttempt.application_id == application_id,
            SubmissionAttempt.status.in_(ACTIVE_SUBMISSION_ATTEMPT_STATUSES),
        )
        .order_by(SubmissionAttempt.id.desc())
        .first()
    )


def reserve_submission_attempt(
    db: Session,
    application: Application,
    approval: SubmissionApproval,
    *,
    task_id: str,
) -> tuple[SubmissionAttempt, bool]:
    existing = (
        db.query(SubmissionAttempt)
        .filter(SubmissionAttempt.approval_reference == approval.reference)
        .first()
    )
    if existing:
        return existing, False

    active = active_submission_attempt(db, application.id)
    if active:
        raise SubmissionAttemptReservationError(
            f"Application already has active submission attempt {active.reference}."
        )

    binding_hash = approval_submission_binding_hash(approval)
    stored_binding = str((approval.approval_metadata or {}).get("submission_binding_hash") or "")
    if stored_binding and stored_binding != binding_hash:
        raise SubmissionAttemptReservationError("Approval binding hash is inconsistent.")

    attempt = SubmissionAttempt(
        application_id=application.id,
        user_id=application.user_id,
        approval_reference=approval.reference,
        attempt_number=int(application.submission_attempt_count or 0) + 1,
        task_id=task_id,
        status=SubmissionAttemptStatus.queued.value,
        binding_hash=binding_hash,
        identity_digest=application_identity_digest(db, application),
        combined_payload_hash=approval.combined_payload_hash,
        adapter_version=(approval.approval_metadata or {}).get("adapter_version"),
        target_identity_hash=(approval.approval_metadata or {}).get("target_identity_hash"),
        attempt_metadata={
            "approval_status_at_reservation": approval.status,
            "submission_idempotency_key": approval.submission_idempotency_key,
        },
    )
    db.add(attempt)
    db.flush()
    db.add(ApplicationEvent(
        application_id=application.id,
        event_type="submission_attempt_reserved",
        from_state=application.automation_state,
        to_state=application.automation_state,
        payload={
            "attempt_reference": attempt.reference,
            "attempt_number": attempt.attempt_number,
            "approval_reference": approval.reference,
            "task_id": task_id,
            "binding_hash": binding_hash,
            "identity_digest": attempt.identity_digest,
        },
    ))
    return attempt, True


def claim_submission_attempt(
    db: Session,
    application: Application,
    approval: SubmissionApproval,
    *,
    attempt_reference: str,
) -> tuple[Optional[SubmissionAttempt], bool]:
    attempt = (
        db.query(SubmissionAttempt)
        .filter(
            SubmissionAttempt.reference == attempt_reference,
            SubmissionAttempt.application_id == application.id,
            SubmissionAttempt.approval_reference == approval.reference,
        )
        .first()
    )
    if not attempt:
        return None, False
    expected_binding = approval_submission_binding_hash(approval)
    if attempt.binding_hash != expected_binding:
        attempt.status = SubmissionAttemptStatus.blocked.value
        attempt.completed_at = datetime.utcnow()
        attempt.attempt_metadata = {
            **dict(attempt.attempt_metadata or {}),
            "block_reason": "approval_binding_changed",
            "observed_binding_hash": expected_binding,
        }
        db.flush()
        return attempt, False

    started_at = datetime.utcnow()
    updated = (
        db.query(SubmissionAttempt)
        .filter(
            SubmissionAttempt.id == attempt.id,
            SubmissionAttempt.status == SubmissionAttemptStatus.queued.value,
        )
        .update(
            {
                SubmissionAttempt.status: SubmissionAttemptStatus.in_progress.value,
                SubmissionAttempt.started_at: started_at,
            },
            synchronize_session=False,
        )
    )
    db.flush()
    refreshed = db.query(SubmissionAttempt).filter(SubmissionAttempt.id == attempt.id).first()
    if updated == 1 and refreshed:
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="submission_attempt_claimed",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "attempt_reference": refreshed.reference,
                "attempt_number": refreshed.attempt_number,
                "approval_reference": approval.reference,
            },
        ))
        return refreshed, True
    return refreshed, False


def finalize_submission_attempt(
    db: Session,
    attempt: SubmissionAttempt,
    *,
    status: SubmissionAttemptStatus | str,
    result: Optional[Mapping[str, Any]] = None,
) -> SubmissionAttempt:
    value = status.value if isinstance(status, SubmissionAttemptStatus) else str(status)
    attempt.status = value
    attempt.completed_at = datetime.utcnow()
    attempt.attempt_metadata = {
        **dict(attempt.attempt_metadata or {}),
        "result": dict(result or {}),
    }
    db.add(ApplicationEvent(
        application_id=attempt.application_id,
        event_type="submission_attempt_finalized",
        from_state=None,
        to_state=None,
        payload={
            "attempt_reference": attempt.reference,
            "attempt_number": attempt.attempt_number,
            "approval_reference": attempt.approval_reference,
            "attempt_status": value,
        },
    ))
    return attempt


def submission_attempt_replay_result(attempt: SubmissionAttempt) -> Dict[str, Any]:
    return {
        "success": attempt.status == SubmissionAttemptStatus.succeeded.value,
        "idempotent": True,
        "duplicate_final_action_prevented": True,
        "automatic_retry_allowed": False,
        "application_id": attempt.application_id,
        "attempt_reference": attempt.reference,
        "attempt_number": attempt.attempt_number,
        "approval_reference": attempt.approval_reference,
        "attempt_status": attempt.status,
        "task_id": attempt.task_id,
    }


__all__ = [
    "DuplicateSubmissionIdentityError",
    "SubmissionAttemptReservationError",
    "active_submission_attempt",
    "application_identity_digest",
    "approval_submission_binding_hash",
    "build_application_idempotency_key",
    "build_submission_identity_aliases",
    "canonicalize_submission_url",
    "claim_submission_attempt",
    "claim_submission_identity_aliases",
    "evidence_fingerprint",
    "finalize_submission_attempt",
    "find_existing_application_for_aliases",
    "find_submission_identity_conflict",
    "prepare_submission_evidence_receipt",
    "register_submission_evidence_receipt",
    "reserve_submission_attempt",
    "submission_attempt_replay_result",
]
