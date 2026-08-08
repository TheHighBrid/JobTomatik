"""Phase 10 evidence ledger and fail-closed release readiness evaluator.

This module deliberately separates *evidence*, *review*, *authorization*, and
*runtime enablement*. A green readiness result or owner authorization never
changes ``ALLOW_REAL_APPLICATION_SUBMIT``, ``AUTOPILOT_ENABLED``, or a platform
kill switch. Those remain independent operational controls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.certification import CertificationEvidence, ReleaseAuthorization
from app.services.ats_manifest import ats_certification_manifest
from app.services.operations_policy import operations_readiness_manifest


EVIDENCE_VERSION = "phase10-certification-v1"
COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)

SHADOW_4H_SECONDS = 4 * 60 * 60
SHADOW_8H_SECONDS = 8 * 60 * 60
SHADOW_24H_SECONDS = 24 * 60 * 60

EVIDENCE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "supervised_real_submission": {
        "description": "Human-reviewed real submission pilot completed with retained evidence.",
    },
    "zero_false_submission_audit": {
        "description": "Pilot review found zero false-positive submitted records.",
    },
    "duplicate_prevention": {
        "description": "Duplicate submission prevention and idempotency evidence passed.",
    },
    "confirmation_evidence": {
        "description": "Independent submission-confirmation evidence was verified.",
    },
    "recovery_incident_drill": {
        "description": "Crash recovery, rollback, and incident-response drill passed.",
    },
    "dead_letter_checkpoint_recovery": {
        "description": (
            "Irrecoverable bounded work was dead-lettered and a retained checkpoint "
            "was safely requeued while checkpoint drift failed closed."
        ),
    },
    "handoff_notifications": {
        "description": "Human-only handoff notifications are operational and reviewable.",
    },
    "policy_controls": {
        "description": "Caps, quiet hours, exclusions, circuit breakers, and kill switches are verified.",
    },
    "monitoring_alerting": {
        "description": "Operational monitoring and alert surfaces are verified for the candidate head.",
    },
    "shadow_run_4h": {
        "description": "Unattended no-submit shadow run retained for at least four hours.",
        "minimum_duration_seconds": SHADOW_4H_SECONDS,
    },
    "shadow_run_8h": {
        "description": "Unattended no-submit shadow run retained for at least eight hours.",
        "minimum_duration_seconds": SHADOW_8H_SECONDS,
    },
    "shadow_run_24h": {
        "description": "Unattended no-submit shadow run retained for at least twenty-four hours.",
        "minimum_duration_seconds": SHADOW_24H_SECONDS,
    },
    "autonomous_pilot": {
        "description": "Separately authorized bounded autonomous pilot completed successfully.",
    },
    "android_device_acceptance": {
        "description": "Exact-head Android runtime acceptance completed on the supported device profile.",
    },
    "release_artifact": {
        "description": "Exact-head release artifact identity was retained.",
    },
    "release_checksum": {
        "description": "Release artifact checksum was independently retained and verified.",
    },
}

AUTONOMOUS_PILOT_REQUIREMENTS: tuple[str, ...] = (
    "supervised_real_submission",
    "zero_false_submission_audit",
    "duplicate_prevention",
    "confirmation_evidence",
    "recovery_incident_drill",
    "dead_letter_checkpoint_recovery",
    "handoff_notifications",
    "policy_controls",
    "monitoring_alerting",
    "shadow_run_4h",
    "shadow_run_8h",
    "shadow_run_24h",
)

V2_RELEASE_REQUIREMENTS: tuple[str, ...] = (
    *AUTONOMOUS_PILOT_REQUIREMENTS,
    "autonomous_pilot",
    "android_device_acceptance",
    "release_artifact",
    "release_checksum",
)

SCOPE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "autonomous_pilot": AUTONOMOUS_PILOT_REQUIREMENTS,
    "v2_release": V2_RELEASE_REQUIREMENTS,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_revision() -> str:
    """Return a commit identity without inventing one when the checkout is unknown."""
    for name in ("JOBTOMATIK_RUNTIME_REVISION", "GITHUB_SHA"):
        value = str(os.getenv(name) or "").strip().lower()
        if COMMIT_RE.fullmatch(value):
            return value
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip().lower()
    except Exception:
        return "unknown"
    return value if COMMIT_RE.fullmatch(value) else "unknown"


def evidence_payload(
    *,
    evidence_type: str,
    adapter: str | None,
    commit_sha: str,
    environment: str,
    status: str,
    duration_seconds: int | None,
    source_reference: str,
    evidence_metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": EVIDENCE_VERSION,
        "evidence_type": evidence_type,
        "adapter": adapter,
        "commit_sha": commit_sha.lower(),
        "environment": environment,
        "status": status,
        "duration_seconds": duration_seconds,
        "source_reference": source_reference,
        "evidence_metadata": evidence_metadata,
    }


def evidence_key_for(
    payload: dict[str, Any],
    *,
    owner_user_id: int | None = None,
) -> str:
    """Return an evidence identity scoped to the owning account or system source.

    Evidence payloads may legitimately have identical external source references for
    different accounts. Namespacing the identity prevents one account from reserving
    another account's otherwise-valid evidence key.
    """

    identity = {
        "owner_scope": (
            f"user:{int(owner_user_id)}" if owner_user_id is not None else "system"
        ),
        "evidence_type": payload["evidence_type"],
        "adapter": payload.get("adapter"),
        "commit_sha": payload["commit_sha"],
        "environment": payload["environment"],
        "source_reference": payload["source_reference"],
    }
    return f"cert:{canonical_hash(identity)}"


def evidence_integrity_ok(record: CertificationEvidence) -> bool:
    payload = evidence_payload(
        evidence_type=record.evidence_type,
        adapter=record.adapter,
        commit_sha=record.commit_sha,
        environment=record.environment,
        status=record.status,
        duration_seconds=record.duration_seconds,
        source_reference=record.source_reference,
        evidence_metadata=dict(record.evidence_metadata or {}),
    )
    return canonical_hash(payload) == record.payload_hash


def evidence_is_qualifying(
    record: CertificationEvidence,
    *,
    revision: str,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    current = ensure_aware(now) or utc_now()
    reasons: list[str] = []
    if record.status != "passed":
        reasons.append("status_not_passed")
    if record.review_status != "verified":
        reasons.append("not_independently_verified")
    if str(record.commit_sha or "").lower() != revision.lower():
        reasons.append("not_exact_candidate_head")
    expires_at = ensure_aware(record.expires_at)
    if expires_at is not None and expires_at <= current:
        reasons.append("evidence_expired")
    if not evidence_integrity_ok(record):
        reasons.append("payload_hash_mismatch")
    requirement = EVIDENCE_REQUIREMENTS.get(record.evidence_type) or {}
    minimum = requirement.get("minimum_duration_seconds")
    if minimum is not None and int(record.duration_seconds or 0) < int(minimum):
        reasons.append("duration_below_minimum")
    return not reasons, reasons


def _latest_records(
    db: Session,
    *,
    user_id: int,
    evidence_types: Iterable[str],
    adapter: str | None,
) -> dict[str, CertificationEvidence]:
    wanted = set(evidence_types)
    query = db.query(CertificationEvidence).filter(
        CertificationEvidence.evidence_type.in_(wanted),
        or_(
            CertificationEvidence.recorded_by_user_id == user_id,
            CertificationEvidence.recorded_by_user_id.is_(None),
        ),
    )
    if adapter:
        query = query.filter(
            (CertificationEvidence.adapter == adapter)
            | (CertificationEvidence.adapter.is_(None))
        )
    rows = query.order_by(
        CertificationEvidence.created_at.desc(),
        CertificationEvidence.id.desc(),
    ).all()
    selected: dict[str, CertificationEvidence] = {}
    for row in rows:
        if row.evidence_type not in selected:
            selected[row.evidence_type] = row
    return selected


def authorization_payload(
    *,
    scope: str,
    release_version: str,
    commit_sha: str,
    approved_by_user_id: int,
    approval_reference: str,
    expires_at: datetime | None,
) -> dict[str, Any]:
    return {
        "version": EVIDENCE_VERSION,
        "scope": scope,
        "release_version": release_version,
        "commit_sha": commit_sha,
        "approved_by_user_id": approved_by_user_id,
        "approval_reference": approval_reference,
        "expires_at": ensure_aware(expires_at).isoformat() if expires_at else None,
    }


def authorization_integrity_ok(record: ReleaseAuthorization) -> bool:
    payload = authorization_payload(
        scope=record.scope,
        release_version=record.release_version,
        commit_sha=record.commit_sha,
        approved_by_user_id=record.approved_by_user_id,
        approval_reference=record.approval_reference,
        expires_at=ensure_aware(record.expires_at),
    )
    return canonical_hash(payload) == record.payload_hash


def active_authorization(
    db: Session,
    *,
    user_id: int,
    scope: str,
    release_version: str,
    revision: str,
    now: datetime | None = None,
) -> ReleaseAuthorization | None:
    current = ensure_aware(now) or utc_now()
    rows = (
        db.query(ReleaseAuthorization)
        .filter(
            ReleaseAuthorization.scope == scope,
            ReleaseAuthorization.release_version == release_version,
            ReleaseAuthorization.commit_sha == revision,
            ReleaseAuthorization.status == "approved",
            ReleaseAuthorization.approved_by_user_id == user_id,
        )
        .order_by(ReleaseAuthorization.approved_at.desc(), ReleaseAuthorization.id.desc())
        .all()
    )
    for row in rows:
        expires_at = ensure_aware(row.expires_at)
        if not authorization_integrity_ok(row):
            continue
        if row.revoked_at is None and (expires_at is None or expires_at > current):
            return row
    return None


def build_release_track(
    db: Session,
    *,
    user_id: int,
    scope: str,
    release_version: str,
    revision: str,
    adapter: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    required = SCOPE_REQUIREMENTS[scope]
    records = _latest_records(
        db,
        user_id=user_id,
        evidence_types=required,
        adapter=adapter,
    )
    evidence: dict[str, Any] = {}
    blockers: list[str] = []

    for evidence_type in required:
        row = records.get(evidence_type)
        if row is None:
            evidence[evidence_type] = {
                "qualifying": False,
                "reasons": ["missing"],
                "description": EVIDENCE_REQUIREMENTS[evidence_type]["description"],
            }
            blockers.append(f"{evidence_type}:missing")
            continue
        qualifying, reasons = evidence_is_qualifying(row, revision=revision, now=now)
        evidence[evidence_type] = {
            "evidence_id": row.id,
            "qualifying": qualifying,
            "reasons": reasons,
            "status": row.status,
            "review_status": row.review_status,
            "commit_sha": row.commit_sha,
            "adapter": row.adapter,
            "environment": row.environment,
            "duration_seconds": row.duration_seconds,
            "source_reference": row.source_reference,
            "created_at": ensure_aware(row.created_at),
            "expires_at": ensure_aware(row.expires_at),
            "description": EVIDENCE_REQUIREMENTS[evidence_type]["description"],
        }
        if not qualifying:
            blockers.extend(f"{evidence_type}:{reason}" for reason in reasons)

    authorization = active_authorization(
        db,
        user_id=user_id,
        scope=scope,
        release_version=release_version,
        revision=revision,
        now=now,
    )
    prerequisites_ready = not blockers
    authorized = authorization is not None
    if not authorized:
        blockers.append("owner_authorization:missing")

    return {
        "scope": scope,
        "release_version": release_version,
        "candidate_revision": revision,
        "adapter": adapter,
        "prerequisites_ready": prerequisites_ready,
        "owner_authorized": authorized,
        "ready": prerequisites_ready and authorized,
        "blockers": blockers,
        "evidence": evidence,
        "authorization": (
            {
                "authorization_id": authorization.id,
                "approval_reference": authorization.approval_reference,
                "approved_at": ensure_aware(authorization.approved_at),
                "expires_at": ensure_aware(authorization.expires_at),
            }
            if authorization is not None
            else None
        ),
        "runtime_enablement_changed": False,
    }


def build_certification_scale_manifest(
    db: Session,
    *,
    user_id: int,
    release_version: str = "v2.00",
    adapter: str | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    candidate_revision = str(revision or current_revision()).lower()
    operations = operations_readiness_manifest()
    ats = ats_certification_manifest()
    settings = get_settings()

    tracks = {
        scope: build_release_track(
            db,
            user_id=user_id,
            scope=scope,
            release_version=release_version,
            revision=candidate_revision,
            adapter=adapter,
        )
        for scope in ("autonomous_pilot", "v2_release")
    }
    return {
        "version": EVIDENCE_VERSION,
        "generated_at": utc_now(),
        "release_version": release_version,
        "candidate_revision": candidate_revision,
        "candidate_revision_known": candidate_revision != "unknown",
        "adapter": adapter,
        "tracks": tracks,
        "runtime_controls": {
            "real_submission_enabled": bool(settings.allow_real_application_submit),
            "autopilot_enabled": bool(operations.get("autopilot_enabled")),
            "global_kill_switch": bool(operations.get("global_kill_switch")),
            "disabled_platforms": list(operations.get("disabled_platforms") or []),
        },
        "adapter_maturity": {
            item.get("name"): item.get("maturity")
            for item in ats.get("adapters", [])
            if isinstance(item, dict)
        },
        "invariants": {
            "recording_evidence_never_enables_submission": True,
            "reviewing_evidence_never_enables_submission": True,
            "owner_authorization_never_enables_submission": True,
            "exact_candidate_head_required": True,
            "expired_or_tampered_evidence_fails_closed": True,
            "shadow_duration_is_measured_not_inferred": True,
            "owner_authorization_is_commit_bound": True,
            "owner_authorization_hash_integrity_required": True,
            "evidence_identity_is_account_namespaced": True,
            "runtime_kill_switches_remain_independent": True,
            "certification_evidence_is_account_scoped": True,
            "dead_letter_checkpoint_recovery_is_separate_evidence": True,
        },
    }


def default_authorization_expiry(scope: str, *, now: datetime | None = None) -> datetime:
    current = ensure_aware(now) or utc_now()
    # Live pilot permission should be intentionally short. Release authorization can
    # survive long enough to complete artifact publication while remaining bounded.
    return current + (timedelta(hours=4) if scope == "autonomous_pilot" else timedelta(hours=24))


__all__ = [
    "AUTONOMOUS_PILOT_REQUIREMENTS",
    "EVIDENCE_REQUIREMENTS",
    "EVIDENCE_VERSION",
    "SCOPE_REQUIREMENTS",
    "V2_RELEASE_REQUIREMENTS",
    "active_authorization",
    "authorization_integrity_ok",
    "authorization_payload",
    "build_certification_scale_manifest",
    "build_release_track",
    "canonical_hash",
    "current_revision",
    "default_authorization_expiry",
    "ensure_aware",
    "evidence_integrity_ok",
    "evidence_is_qualifying",
    "evidence_key_for",
    "evidence_payload",
    "utc_now",
]
