"""One-shot signed Android runtime update requests.

This module deliberately reuses the canonical pilot-control signer, request slot,
receipt format, and no-replay lifecycle. It does not add a shell executor. The only
new native action is the fixed ``jobtomatik update`` operation, and it is allowed
only while the supervised Lever lease is inactive and the authenticated owner has
no queued or in-progress submission attempt.

An ``uncertain`` attempt remains quarantined from material mutation and retry by the
submission-integrity boundary, but it is not an executing process. Treating every
historical uncertainty as a runtime-maintenance lock would permanently deadlock a
safely quarantined application such as Fullscript 246.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.models.user import User
from app.services.lever_pilot_control_request import (
    CONTROL_SCHEMA_VERSION,
    HEARTBEAT_PATH,
    INFLIGHT_PATH,
    REQUEST_PATH,
    REQUEST_TTL_SECONDS,
    STATUS_PATH,
    LeverPilotControlError,
    _assert_request_slot_available,
    _atomic_write_json,
    _heartbeat_fresh,
    _now,
    _read_json,
    _record_signature_valid,
    _request_is_expired,
    _request_publication_lock,
    _runtime_revision_from_environment,
    _sanitize_request,
    _settings_secret,
    _signed_record,
    _unlink,
    _write_status,
)
from app.services.supervised_runtime_mode import runtime_lease_status


UPDATE_ACTION = "update"
NATIVE_CONTROL_ACTIONS = frozenset({"arm", "disarm", UPDATE_ACTION})
EXECUTING_SUBMISSION_ATTEMPT_STATUSES = (
    SubmissionAttemptStatus.queued.value,
    SubmissionAttemptStatus.in_progress.value,
)


def _owner_has_executing_submission_attempt(
    db: Session,
    user: User,
) -> bool:
    return bool(
        db.query(SubmissionAttempt.id)
        .filter(
            SubmissionAttempt.user_id == user.id,
            SubmissionAttempt.status.in_(EXECUTING_SUBMISSION_ATTEMPT_STATUSES),
        )
        .count()
    )


def _assert_runtime_update_safe(
    db: Session,
    user: User,
    *,
    runtime_revision: str,
) -> None:
    if runtime_lease_status(expected_revision=runtime_revision).get("active"):
        raise LeverPilotControlError("ANDROID_RUNTIME_UPDATE_SUPERVISED_WINDOW_ACTIVE")
    if _owner_has_executing_submission_attempt(db, user):
        raise LeverPilotControlError(
            "ANDROID_RUNTIME_UPDATE_EXECUTING_SUBMISSION_ATTEMPT"
        )


def _create_update_request(
    db: Session,
    user: User,
    *,
    runtime_revision: str,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, Any]:
    secret = _settings_secret()
    with _request_publication_lock(request_path):
        _assert_request_slot_available(
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
            secret_key=secret,
        )
        # Recheck at the serialized publication boundary so an update request cannot
        # be published from a stale safe-state observation.
        _assert_runtime_update_safe(db, user, runtime_revision=runtime_revision)
        now = _now()
        payload = {
            "schema_version": CONTROL_SCHEMA_VERSION,
            "request_id": "runtime-update-" + secrets.token_urlsafe(18),
            "action": UPDATE_ACTION,
            "application_id": None,
            "user_id": int(user.id),
            "runtime_revision": runtime_revision,
            "created_at_epoch": now,
            "expires_at_epoch": now + REQUEST_TTL_SECONDS,
        }
        record = _signed_record(payload, secret)
        _atomic_write_json(request_path, record)
    return _sanitize_request(record) or {}


def request_runtime_update(
    db: Session,
    user: User,
    *,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
    heartbeat_path: Path = HEARTBEAT_PATH,
) -> dict[str, Any]:
    """Publish one explicit fixed-action update request for the native controller."""

    revision = _runtime_revision_from_environment()
    if not _heartbeat_fresh(heartbeat_path):
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_NATIVE_CONTROLLER_UNAVAILABLE")
    _assert_runtime_update_safe(db, user, runtime_revision=revision)
    request = _create_update_request(
        db,
        user,
        runtime_revision=revision,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    return {
        "accepted": True,
        "request": request,
        "runtime_update_requested": True,
        "submission_approval_issued": False,
        "submission_queued": False,
        "persisted_runtime_flags_changed": False,
    }


def claim_native_control_request(
    db: Session,
    *,
    runtime_revision: str,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, Any] | None:
    """Claim arm, disarm, or update from the single serialized native-control slot.

    Arm/disarm semantics are preserved. Update receives an additional claim-time
    safety check immediately before the request becomes inflight.
    """

    secret = _settings_secret()
    request_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(request_path.parent, 0o700)
    with _request_publication_lock(request_path):
        request = _read_json(request_path)
        if not request:
            return None
        if not _record_signature_valid(request, secret):
            _unlink(request_path)
            return None
        if request.get("schema_version") != CONTROL_SCHEMA_VERSION:
            _write_status(
                request,
                outcome="rejected_invalid_request",
                status_path=status_path,
                secret_key=secret,
            )
            _unlink(request_path)
            return None

        action = str(request.get("action") or "")
        if action not in NATIVE_CONTROL_ACTIONS:
            _write_status(
                request,
                outcome="rejected_invalid_request",
                status_path=status_path,
                secret_key=secret,
            )
            _unlink(request_path)
            return None
        if str(request.get("runtime_revision") or "").lower() != str(runtime_revision).lower():
            _write_status(
                request,
                outcome="rejected_invalid_request",
                status_path=status_path,
                secret_key=secret,
            )
            _unlink(request_path)
            return None
        if _request_is_expired(request):
            _write_status(
                request,
                outcome="expired",
                status_path=status_path,
                secret_key=secret,
            )
            _unlink(request_path)
            return None
        if inflight_path.exists():
            raise LeverPilotControlError("LEVER_PILOT_CONTROL_INFLIGHT_EXISTS_NO_REPLAY")

        if action == UPDATE_ACTION:
            try:
                request_user_id = int(request.get("user_id"))
            except (TypeError, ValueError):
                request_user_id = 0
            if request_user_id <= 0:
                _write_status(
                    request,
                    outcome="rejected_invalid_request",
                    status_path=status_path,
                    secret_key=secret,
                )
                _unlink(request_path)
                return None
            request_user = db.query(User).filter(User.id == request_user_id).first()
            if not request_user:
                _write_status(
                    request,
                    outcome="rejected_invalid_request",
                    status_path=status_path,
                    secret_key=secret,
                )
                _unlink(request_path)
                return None
            try:
                _assert_runtime_update_safe(
                    db,
                    request_user,
                    runtime_revision=runtime_revision,
                )
            except LeverPilotControlError:
                _write_status(
                    request,
                    outcome="failed",
                    status_path=status_path,
                    secret_key=secret,
                )
                _unlink(request_path)
                return None

        os.replace(request_path, inflight_path)
        directory_fd = os.open(str(inflight_path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return request


__all__ = [
    "EXECUTING_SUBMISSION_ATTEMPT_STATUSES",
    "NATIVE_CONTROL_ACTIONS",
    "UPDATE_ACTION",
    "claim_native_control_request",
    "request_runtime_update",
]
