"""Signed app-to-native control requests for the supervised Lever Android window.

The backend never executes native Termux commands directly. Authenticated UI actions create
short-lived HMAC-signed request files in the shared Termux/PRoot /tmp. A native controller
claims each request exactly once and delegates only to the existing fail-closed
``jobtomatik-pilot`` wrapper.

No request grants a submission approval, changes persisted live-submit flags, or authorizes
an unattended application. The active process-bound runtime lease remains the source of
truth after a native transition.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from typing import Any, Iterator, Mapping

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import Application
from app.models.job import Job
from app.models.submission_integrity import (
    ACTIVE_SUBMISSION_ATTEMPT_STATUSES,
    SubmissionAttempt,
)
from app.models.user import User
from app.services.application_state import normalize_state
from app.services.supervised_runtime_mode import REVISION_RE, runtime_lease_status
from app.services.supervised_target_identity import persisted_supervised_target_metadata


CONTROL_SCHEMA_VERSION = 1
CONTROL_DIR = Path("/tmp/jobtomatik-pilot-control")
REQUEST_PATH = CONTROL_DIR / "request.json"
INFLIGHT_PATH = CONTROL_DIR / "inflight.json"
STATUS_PATH = CONTROL_DIR / "status.json"
OWNER_PATH = CONTROL_DIR / "lease-owner.json"
HEARTBEAT_PATH = CONTROL_DIR / "controller-heartbeat"
REQUEST_TTL_SECONDS = 90
CONTROLLER_HEARTBEAT_TTL_SECONDS = 8
ARM_ACK_PREFIX = "ENABLE LEVER SUPERVISED WINDOW"
VALID_ACTIONS = frozenset({"arm", "disarm"})
VALID_OUTCOMES = frozenset(
    {
        "success",
        "failed",
        "expired",
        "rejected_invalid_request",
        "uncertain_no_replay",
    }
)


class LeverPilotControlError(RuntimeError):
    pass


def _now() -> int:
    return int(time.time())


def _runtime_revision_from_environment() -> str:
    revision = str(os.environ.get("JOBTOMATIK_RUNTIME_REVISION") or "").strip().lower()
    expected = str(os.environ.get("JOBTOMATIK_EXPECTED_REVISION") or "").strip().lower()
    runtime_mode = str(os.environ.get("JOBTOMATIK_RUNTIME_MODE") or "").strip().lower()
    runtime_role = str(os.environ.get("JOBTOMATIK_RUNTIME_ROLE") or "").strip().lower()
    if runtime_mode != "android_managed" or runtime_role != "api":
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_ANDROID_MANAGED_API_REQUIRED")
    if not REVISION_RE.fullmatch(revision) or expected != revision:
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_RUNTIME_REVISION_UNATTESTED")
    return revision


def _ensure_control_dir(path: Path = CONTROL_DIR) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _canonical_payload(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _signature(payload: Mapping[str, Any], secret_key: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        _canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()


def _signed_record(payload: Mapping[str, Any], secret_key: str) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    return {
        **unsigned,
        "signature": _signature(unsigned, secret_key),
    }


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    _ensure_control_dir(path.parent)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(value), handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _request_publication_lock(request_path: Path) -> Iterator[None]:
    """Serialize the single request slot across API workers and the native bridge."""

    _ensure_control_dir(request_path.parent)
    lock_path = request_path.with_name("request.lock")
    with open(lock_path, "a+", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _record_signature_valid(record: Mapping[str, Any] | None, secret_key: str) -> bool:
    if not isinstance(record, Mapping):
        return False
    signature = str(record.get("signature") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    unsigned = dict(record)
    unsigned.pop("signature", None)
    return hmac.compare_digest(signature, _signature(unsigned, secret_key))


def _settings_secret() -> str:
    settings = get_settings()
    if settings.uses_placeholder_secret:
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_SAFE_SECRET_REQUIRED")
    return settings.secret_key


def _sanitize_request(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, Mapping):
        return None
    return {
        "request_id": record.get("request_id"),
        "action": record.get("action"),
        "application_id": record.get("application_id"),
        "runtime_revision": record.get("runtime_revision"),
        "created_at_epoch": record.get("created_at_epoch"),
        "expires_at_epoch": record.get("expires_at_epoch"),
    }


def _sanitize_status(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, Mapping):
        return None
    return {
        "request_id": record.get("request_id"),
        "action": record.get("action"),
        "application_id": record.get("application_id"),
        "outcome": record.get("outcome"),
        "runtime_revision": record.get("runtime_revision"),
        "completed_at_epoch": record.get("completed_at_epoch"),
        "exit_code": record.get("exit_code"),
    }


def _request_is_expired(record: Mapping[str, Any], now: int | None = None) -> bool:
    try:
        expires_at = int(record.get("expires_at_epoch"))
    except (TypeError, ValueError):
        return True
    return expires_at <= int(now if now is not None else _now())


def _write_status(
    request: Mapping[str, Any],
    *,
    outcome: str,
    exit_code: int | None = None,
    status_path: Path = STATUS_PATH,
    secret_key: str | None = None,
) -> dict[str, Any]:
    if outcome not in VALID_OUTCOMES:
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_STATUS_OUTCOME_INVALID")
    secret = secret_key or _settings_secret()
    payload = {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "request_id": request.get("request_id"),
        "action": request.get("action"),
        "application_id": request.get("application_id"),
        "user_id": request.get("user_id"),
        "runtime_revision": request.get("runtime_revision"),
        "outcome": outcome,
        "exit_code": int(exit_code) if exit_code is not None else None,
        "completed_at_epoch": _now(),
    }
    record = _signed_record(payload, secret)
    _atomic_write_json(status_path, record)
    return record


def _write_owner_record(
    request: Mapping[str, Any],
    *,
    owner_path: Path = OWNER_PATH,
    secret_key: str | None = None,
) -> dict[str, Any]:
    secret = secret_key or _settings_secret()
    payload = {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "kind": "lever_supervised_lease_owner",
        "arm_request_id": request.get("request_id"),
        "application_id": request.get("application_id"),
        "user_id": request.get("user_id"),
        "runtime_revision": request.get("runtime_revision"),
        "recorded_at_epoch": _now(),
    }
    record = _signed_record(payload, secret)
    _atomic_write_json(owner_path, record)
    return record


def _owner_record_matches(
    record: Mapping[str, Any] | None,
    *,
    user: User,
    runtime_revision: str,
    secret_key: str,
) -> bool:
    if not _record_signature_valid(record, secret_key):
        return False
    assert record is not None
    try:
        owner_id = int(record.get("user_id"))
    except (TypeError, ValueError):
        return False
    return bool(
        record.get("schema_version") == CONTROL_SCHEMA_VERSION
        and record.get("kind") == "lever_supervised_lease_owner"
        and owner_id == int(user.id)
        and str(record.get("runtime_revision") or "").lower()
        == str(runtime_revision or "").lower()
    )


def _remove_expired_unclaimed_request(
    *,
    request_path: Path = REQUEST_PATH,
    status_path: Path = STATUS_PATH,
    secret_key: str,
) -> None:
    request = _read_json(request_path)
    if not request:
        return
    if not _record_signature_valid(request, secret_key):
        _unlink(request_path)
        return
    if not _request_is_expired(request):
        return
    _write_status(
        request,
        outcome="expired",
        status_path=status_path,
        secret_key=secret_key,
    )
    _unlink(request_path)


def _assert_request_slot_available(
    *,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
    secret_key: str,
) -> None:
    _remove_expired_unclaimed_request(
        request_path=request_path,
        status_path=status_path,
        secret_key=secret_key,
    )
    if request_path.exists():
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_REQUEST_ALREADY_PENDING")
    if inflight_path.exists():
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_REQUEST_INFLIGHT_NO_REPLAY")


def _owned_ready_lever_application(
    db: Session,
    user: User,
    application_id: int,
) -> tuple[Application, Job]:
    application = (
        db.query(Application)
        .filter(
            Application.id == application_id,
            Application.user_id == user.id,
        )
        .with_for_update()
        .first()
    )
    if not application:
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_APPLICATION_NOT_FOUND")
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_APPLICATION_JOB_MISSING")

    state = normalize_state(application.automation_state)
    if state != "ready_to_apply":
        raise LeverPilotControlError(
            f"LEVER_PILOT_CONTROL_APPLICATION_NOT_READY state={state}"
        )

    target = persisted_supervised_target_metadata(job)
    if target.get("verified") is not True:
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_TARGET_IDENTITY_UNVERIFIED")
    if str(target.get("platform") or "").strip().lower() != "lever":
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_TARGET_NOT_LEVER")
    if not str(target.get("posting_id") or "").strip():
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_TARGET_IDENTITY_INCOMPLETE")

    active_attempt_count = (
        db.query(SubmissionAttempt.id)
        .filter(
            SubmissionAttempt.application_id == application.id,
            SubmissionAttempt.status.in_(ACTIVE_SUBMISSION_ATTEMPT_STATUSES),
        )
        .count()
    )
    if active_attempt_count:
        raise LeverPilotControlError(
            "LEVER_PILOT_CONTROL_ACTIVE_OR_UNCERTAIN_SUBMISSION_ATTEMPT"
        )
    return application, job


def _create_request(
    *,
    action: str,
    user: User,
    runtime_revision: str,
    application_id: int | None,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, Any]:
    if action not in VALID_ACTIONS:
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_ACTION_INVALID")
    secret = _settings_secret()
    with _request_publication_lock(request_path):
        _assert_request_slot_available(
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
            secret_key=secret,
        )
        now = _now()
        payload = {
            "schema_version": CONTROL_SCHEMA_VERSION,
            "request_id": "pilot-control-" + secrets.token_urlsafe(18),
            "action": action,
            "application_id": application_id,
            "user_id": int(user.id),
            "runtime_revision": runtime_revision,
            "created_at_epoch": now,
            "expires_at_epoch": now + REQUEST_TTL_SECONDS,
        }
        record = _signed_record(payload, secret)
        _atomic_write_json(request_path, record)
    return _sanitize_request(record) or {}


def request_runtime_arm(
    db: Session,
    user: User,
    *,
    application_id: int,
    acknowledgment: str,
    owner_path: Path = OWNER_PATH,
) -> dict[str, Any]:
    revision = _runtime_revision_from_environment()
    expected_ack = f"{ARM_ACK_PREFIX} {application_id}"
    if str(acknowledgment or "").strip() != expected_ack:
        raise LeverPilotControlError(
            "LEVER_PILOT_CONTROL_ARM_ACKNOWLEDGMENT_REQUIRED"
        )
    _owned_ready_lever_application(db, user, application_id)
    if not _heartbeat_fresh():
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_NATIVE_CONTROLLER_UNAVAILABLE")
    if runtime_lease_status(expected_revision=revision).get("active"):
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_RUNTIME_ALREADY_ACTIVE")
    # A prior lease on the same revision may have expired without an explicit disarm.
    # Clear that stale receipt before publishing a new arm request so an interrupted
    # new arm can never inherit another account's old disarm authority.
    _unlink(owner_path)
    return {
        "accepted": True,
        "request": _create_request(
            action="arm",
            user=user,
            runtime_revision=revision,
            application_id=application_id,
        ),
        "submission_approval_issued": False,
        "submission_queued": False,
        "persisted_runtime_flags_changed": False,
    }


def request_runtime_disarm(
    user: User,
    *,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
    owner_path: Path = OWNER_PATH,
) -> dict[str, Any]:
    revision = _runtime_revision_from_environment()
    if not _heartbeat_fresh():
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_NATIVE_CONTROLLER_UNAVAILABLE")
    if not runtime_lease_status(expected_revision=revision).get("active"):
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_RUNTIME_NOT_ACTIVE")
    secret = _settings_secret()
    owner_record = _read_json(owner_path)
    if not _owner_record_matches(
        owner_record,
        user=user,
        runtime_revision=revision,
        secret_key=secret,
    ):
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_DISARM_OWNER_REQUIRED")
    return {
        "accepted": True,
        "request": _create_request(
            action="disarm",
            user=user,
            runtime_revision=revision,
            application_id=None,
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
        ),
        "submission_approval_issued": False,
        "submission_queued": False,
        "persisted_runtime_flags_changed": False,
    }


def _heartbeat_fresh(path: Path = HEARTBEAT_PATH, now: int | None = None) -> bool:
    try:
        age = int(now if now is not None else _now()) - int(path.stat().st_mtime)
    except OSError:
        return False
    return 0 <= age <= CONTROLLER_HEARTBEAT_TTL_SECONDS


def runtime_control_status(
    user: User,
    *,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
    owner_path: Path = OWNER_PATH,
    heartbeat_path: Path = HEARTBEAT_PATH,
) -> dict[str, Any]:
    try:
        revision = _runtime_revision_from_environment()
        runtime_available = True
    except LeverPilotControlError:
        revision = None
        runtime_available = False

    try:
        secret = _settings_secret()
    except LeverPilotControlError:
        secret = None

    request = _read_json(request_path)
    inflight = _read_json(inflight_path)
    status_record = _read_json(status_path)
    owner_record = _read_json(owner_path)
    if secret is not None:
        if request and not _record_signature_valid(request, secret):
            request = None
        if inflight and not _record_signature_valid(inflight, secret):
            inflight = None
        if status_record and not _record_signature_valid(status_record, secret):
            status_record = None
        if owner_record and not _record_signature_valid(owner_record, secret):
            owner_record = None
    else:
        request = None
        inflight = None
        status_record = None
        owner_record = None

    def owned(record: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        if not record:
            return None
        try:
            return record if int(record.get("user_id")) == int(user.id) else None
        except (TypeError, ValueError):
            return None

    owned_request = owned(request)
    owned_inflight = owned(inflight)
    owned_status = owned(status_record)

    lease = runtime_lease_status(
        expected_revision=revision,
    ) if revision else {
        "active": False,
        "state": None,
        "expires_at_epoch": None,
        "blockers": ["runtime_revision_unavailable"],
    }

    controller_available = _heartbeat_fresh(heartbeat_path)
    lease_owned_by_current_user = bool(
        lease.get("active")
        and revision
        and secret
        and _owner_record_matches(
            owner_record,
            user=user,
            runtime_revision=revision,
            secret_key=secret,
        )
    )
    transition_state = "idle"
    if lease.get("active"):
        transition_state = "active"
    elif owned_inflight:
        transition_state = "inflight"
    elif owned_request:
        transition_state = "requested"
    elif owned_status and owned_status.get("outcome") == "uncertain_no_replay":
        transition_state = "uncertain_no_replay"
    elif owned_status and owned_status.get("outcome") == "failed":
        transition_state = "failed"

    return {
        "available": bool(runtime_available and controller_available and secret),
        "android_managed_api": runtime_available,
        "controller_available": controller_available,
        "runtime_revision": revision,
        "lease_active": bool(lease.get("active")),
        "lease_state": lease.get("state"),
        "lease_expires_at_epoch": lease.get("expires_at_epoch"),
        "lease_blockers": list(lease.get("blockers") or []),
        "lease_owned_by_current_user": lease_owned_by_current_user,
        "can_disarm": bool(lease_owned_by_current_user and controller_available),
        "transition_state": transition_state,
        "pending_request": _sanitize_request(owned_request),
        "inflight_request": _sanitize_request(owned_inflight),
        "last_result": _sanitize_status(owned_status),
        "submission_approval_issued": False,
        "submission_queued": False,
        "persisted_runtime_flags_changed": False,
    }


def claim_control_request(
    *,
    runtime_revision: str,
    request_path: Path = REQUEST_PATH,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, Any] | None:
    secret = _settings_secret()
    _ensure_control_dir(request_path.parent)
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
        if str(request.get("action") or "") not in VALID_ACTIONS:
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
        os.replace(request_path, inflight_path)
        directory_fd = os.open(str(inflight_path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return request


def complete_control_request(
    *,
    request_id: str,
    outcome: str,
    exit_code: int | None = None,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
    owner_path: Path = OWNER_PATH,
) -> dict[str, Any]:
    secret = _settings_secret()
    request = _read_json(inflight_path)
    if not request or not _record_signature_valid(request, secret):
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_INFLIGHT_INVALID")
    if str(request.get("request_id") or "") != str(request_id or ""):
        raise LeverPilotControlError("LEVER_PILOT_CONTROL_INFLIGHT_REQUEST_MISMATCH")
    status_record = _write_status(
        request,
        outcome=outcome,
        exit_code=exit_code,
        status_path=status_path,
        secret_key=secret,
    )
    action = str(request.get("action") or "")
    if outcome == "success" and action == "arm":
        _write_owner_record(request, owner_path=owner_path, secret_key=secret)
    elif outcome == "success" and action == "disarm":
        _unlink(owner_path)
    _unlink(inflight_path)
    return status_record


def recover_inflight_without_replay(
    *,
    inflight_path: Path = INFLIGHT_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, Any] | None:
    secret = _settings_secret()
    request = _read_json(inflight_path)
    if not request:
        return None
    if not _record_signature_valid(request, secret):
        _unlink(inflight_path)
        return None
    status_record = _write_status(
        request,
        outcome="uncertain_no_replay",
        status_path=status_path,
        secret_key=secret,
    )
    _unlink(inflight_path)
    return status_record


__all__ = [
    "ARM_ACK_PREFIX",
    "CONTROL_DIR",
    "HEARTBEAT_PATH",
    "INFLIGHT_PATH",
    "LeverPilotControlError",
    "OWNER_PATH",
    "REQUEST_PATH",
    "STATUS_PATH",
    "claim_control_request",
    "complete_control_request",
    "recover_inflight_without_replay",
    "request_runtime_arm",
    "request_runtime_disarm",
    "runtime_control_status",
]
