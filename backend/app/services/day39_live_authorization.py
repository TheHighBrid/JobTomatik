"""Persistence and atomic attempt reservation for the Day 39 live pilot.

Creating an authorization never enables real submission. A live worker must separately
pass production policy and runtime safety, then reserve one non-reclaiming attempt here
immediately before consequential browser work.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import update

from app.models.live_pilot import LivePilotAttemptReservation, LivePilotAuthorization
from app.services.day39_live_window import (
    DAY39_LIVE_ADAPTER,
    DAY39_LIVE_ADAPTER_VERSION,
    DAY39_LIVE_WINDOW_VERSION,
    build_day39_live_window_readiness,
)


LIVE_PILOT_AUTHORIZATION_VERSION = "day39-live-pilot-authorization-v1"


def _aware(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def live_pilot_authorization_payload(
    *,
    approved_by_user_id: int,
    adapter: str,
    adapter_version: str,
    commit_sha: str,
    approval_reference: str,
    starts_at: datetime,
    expires_at: datetime,
    max_submission_attempts: int,
    acknowledgment: str,
) -> dict[str, Any]:
    return {
        "version": LIVE_PILOT_AUTHORIZATION_VERSION,
        "readiness_contract_version": DAY39_LIVE_WINDOW_VERSION,
        "approved_by_user_id": int(approved_by_user_id),
        "adapter": str(adapter).strip().lower(),
        "adapter_version": str(adapter_version).strip(),
        "commit_sha": str(commit_sha).strip().lower(),
        "approval_reference": " ".join(str(approval_reference).strip().split()),
        "starts_at": _aware(starts_at).isoformat(),
        "expires_at": _aware(expires_at).isoformat(),
        "max_submission_attempts": int(max_submission_attempts),
        "acknowledgment": str(acknowledgment),
    }


def live_pilot_authorization_integrity_ok(record: LivePilotAuthorization) -> bool:
    metadata = dict(record.authorization_metadata or {})
    acknowledgment = str(metadata.get("acknowledgment") or "")
    payload = live_pilot_authorization_payload(
        approved_by_user_id=int(record.approved_by_user_id),
        adapter=str(record.adapter or ""),
        adapter_version=str(record.adapter_version or ""),
        commit_sha=str(record.commit_sha or ""),
        approval_reference=str(record.approval_reference or ""),
        starts_at=_aware(record.starts_at),
        expires_at=_aware(record.expires_at),
        max_submission_attempts=int(record.max_submission_attempts or 0),
        acknowledgment=acknowledgment,
    )
    return _canonical_hash(payload) == str(record.payload_hash or "")


def create_live_pilot_authorization(
    db,
    *,
    approved_by_user_id: int,
    promotion: Any,
    adapter_state: Any,
    runtime_safety: Any,
    policy_state: Any,
    owner_request: Any,
    now: datetime | None = None,
) -> tuple[LivePilotAuthorization | None, dict[str, Any]]:
    """Persist one exact owner authorization only after the pure readiness gate passes."""

    current = _aware(now)
    report = build_day39_live_window_readiness(
        promotion=promotion,
        adapter_state=adapter_state,
        runtime_safety=runtime_safety,
        policy_state=policy_state,
        owner_request=owner_request,
        now=current,
    )
    if report.get("authorization_eligible") is not True:
        return None, report

    owner = owner_request if isinstance(owner_request, Mapping) else {}
    approval_reference = " ".join(str(owner.get("approval_reference") or "").strip().split())
    existing = (
        db.query(LivePilotAuthorization)
        .filter(
            LivePilotAuthorization.approved_by_user_id == int(approved_by_user_id),
            LivePilotAuthorization.approval_reference == approval_reference,
        )
        .first()
    )

    starts_at = datetime.fromisoformat(str(report["starts_at"]))
    expires_at = datetime.fromisoformat(str(report["expires_at"]))
    payload = live_pilot_authorization_payload(
        approved_by_user_id=int(approved_by_user_id),
        adapter=DAY39_LIVE_ADAPTER,
        adapter_version=DAY39_LIVE_ADAPTER_VERSION,
        commit_sha=str(report["release_candidate_revision"]),
        approval_reference=approval_reference,
        starts_at=starts_at,
        expires_at=expires_at,
        max_submission_attempts=int(report["requested_attempt_cap"]),
        acknowledgment=str(owner.get("acknowledgment") or ""),
    )
    payload_hash = _canonical_hash(payload)

    if existing is not None:
        if str(existing.payload_hash or "") != payload_hash:
            raise ValueError("Live-pilot approval reference already exists with different authority")
        if not live_pilot_authorization_integrity_ok(existing):
            raise ValueError("Existing live-pilot authorization failed integrity validation")
        report = dict(report)
        report["authorization_persisted"] = True
        report["authorization_id"] = int(existing.id)
        report["duplicate"] = True
        return existing, report

    active = (
        db.query(LivePilotAuthorization)
        .filter(
            LivePilotAuthorization.approved_by_user_id == int(approved_by_user_id),
            LivePilotAuthorization.status == "approved",
            LivePilotAuthorization.revoked_at.is_(None),
            LivePilotAuthorization.expires_at > current,
        )
        .first()
    )
    if active is not None:
        report = dict(report)
        report["authorization_eligible"] = False
        report["blockers"] = [*list(report.get("blockers") or []), "database.active_live_window_exists"]
        report["next_action"] = "revoke_or_expire_existing_live_window"
        return None, report

    record = LivePilotAuthorization(
        approved_by_user_id=int(approved_by_user_id),
        adapter=DAY39_LIVE_ADAPTER,
        adapter_version=DAY39_LIVE_ADAPTER_VERSION,
        commit_sha=str(report["release_candidate_revision"]),
        approval_reference=approval_reference,
        payload_hash=payload_hash,
        status="approved",
        starts_at=starts_at,
        expires_at=expires_at,
        max_submission_attempts=int(report["requested_attempt_cap"]),
        reserved_submission_attempts=0,
        approved_at=current,
        authorization_metadata={
            "version": LIVE_PILOT_AUTHORIZATION_VERSION,
            "readiness_report_sha256": report.get("report_sha256"),
            "acknowledgment": str(owner.get("acknowledgment") or ""),
            "runtime_enablement_changed": False,
            "followup_send_authorized": False,
        },
    )
    db.add(record)
    db.flush()

    report = dict(report)
    report["authorization_persisted"] = True
    report["authorization_id"] = int(record.id)
    report["duplicate"] = False
    report["live_window_authorized"] = False
    report["real_submission_enabled"] = False
    return record, report


def active_live_pilot_authorization(
    db,
    *,
    user_id: int,
    adapter: str,
    adapter_version: str,
    revision: str,
    now: datetime | None = None,
) -> LivePilotAuthorization | None:
    """Return a currently active, intact authorization for the exact runtime identity."""

    current = _aware(now)
    rows = (
        db.query(LivePilotAuthorization)
        .filter(
            LivePilotAuthorization.approved_by_user_id == int(user_id),
            LivePilotAuthorization.adapter == str(adapter).strip().lower(),
            LivePilotAuthorization.adapter_version == str(adapter_version).strip(),
            LivePilotAuthorization.commit_sha == str(revision).strip().lower(),
            LivePilotAuthorization.status == "approved",
            LivePilotAuthorization.revoked_at.is_(None),
            LivePilotAuthorization.starts_at <= current,
            LivePilotAuthorization.expires_at > current,
        )
        .order_by(LivePilotAuthorization.approved_at.desc(), LivePilotAuthorization.id.desc())
        .all()
    )
    for row in rows:
        if live_pilot_authorization_integrity_ok(row):
            return row
    return None


def reserve_live_pilot_attempt(
    db,
    *,
    user_id: int,
    application_id: int,
    adapter: str,
    adapter_version: str,
    revision: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically consume at most one durable live-attempt slot for an application.

    Reservations are deliberately not reclaimed after browser failure or uncertain
    confirmation. Retrying the same application may reuse its existing reservation only
    while that exact authorization is still active; a different application must burn a
    new slot.
    """

    current = _aware(now)
    existing = (
        db.query(LivePilotAttemptReservation)
        .filter(LivePilotAttemptReservation.application_id == int(application_id))
        .first()
    )
    if existing is not None:
        authorization = active_live_pilot_authorization(
            db,
            user_id=int(user_id),
            adapter=adapter,
            adapter_version=adapter_version,
            revision=revision,
            now=current,
        )
        if authorization is None or int(authorization.id) != int(existing.authorization_id):
            return {
                "allowed": False,
                "reason": "existing_reservation_not_valid_for_active_authorization",
                "reservation_id": int(existing.id),
            }
        return {
            "allowed": True,
            "reason": "existing_application_reservation_reused",
            "authorization_id": int(authorization.id),
            "reservation_id": int(existing.id),
            "reused": True,
            "attempts_reserved": int(authorization.reserved_submission_attempts or 0),
            "attempt_cap": int(authorization.max_submission_attempts or 0),
        }

    authorization = active_live_pilot_authorization(
        db,
        user_id=int(user_id),
        adapter=adapter,
        adapter_version=adapter_version,
        revision=revision,
        now=current,
    )
    if authorization is None:
        return {"allowed": False, "reason": "active_live_pilot_authorization_missing"}

    statement = (
        update(LivePilotAuthorization)
        .where(
            LivePilotAuthorization.id == int(authorization.id),
            LivePilotAuthorization.status == "approved",
            LivePilotAuthorization.revoked_at.is_(None),
            LivePilotAuthorization.starts_at <= current,
            LivePilotAuthorization.expires_at > current,
            LivePilotAuthorization.reserved_submission_attempts
            < LivePilotAuthorization.max_submission_attempts,
        )
        .values(
            reserved_submission_attempts=LivePilotAuthorization.reserved_submission_attempts + 1
        )
    )
    result = db.execute(statement)
    if int(result.rowcount or 0) != 1:
        return {"allowed": False, "reason": "live_pilot_attempt_cap_exhausted"}

    reservation = LivePilotAttemptReservation(
        authorization_id=int(authorization.id),
        application_id=int(application_id),
        reservation_key=f"live-pilot:{int(authorization.id)}:application:{int(application_id)}",
        reserved_at=current,
        reservation_metadata={
            "adapter": str(adapter).strip().lower(),
            "adapter_version": str(adapter_version).strip(),
            "revision": str(revision).strip().lower(),
            "non_reclaiming": True,
        },
    )
    db.add(reservation)
    db.flush()
    db.refresh(authorization)
    return {
        "allowed": True,
        "reason": "live_pilot_attempt_reserved",
        "authorization_id": int(authorization.id),
        "reservation_id": int(reservation.id),
        "reused": False,
        "attempts_reserved": int(authorization.reserved_submission_attempts or 0),
        "attempt_cap": int(authorization.max_submission_attempts or 0),
    }


def revoke_live_pilot_authorization(
    db,
    *,
    authorization: LivePilotAuthorization,
    reason: str,
    revoked_by_user_id: int,
    now: datetime | None = None,
) -> LivePilotAuthorization:
    current = _aware(now)
    authorization.status = "revoked"
    authorization.revoked_at = current
    metadata = dict(authorization.authorization_metadata or {})
    metadata["revoked_reason"] = " ".join(str(reason).strip().split())
    metadata["revoked_by_user_id"] = int(revoked_by_user_id)
    metadata["reserved_attempts_reclaimed"] = False
    authorization.authorization_metadata = metadata
    db.flush()
    return authorization


__all__ = [
    "LIVE_PILOT_AUTHORIZATION_VERSION",
    "active_live_pilot_authorization",
    "create_live_pilot_authorization",
    "live_pilot_authorization_integrity_ok",
    "live_pilot_authorization_payload",
    "reserve_live_pilot_attempt",
    "revoke_live_pilot_authorization",
]
