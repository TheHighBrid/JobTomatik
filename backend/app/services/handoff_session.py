from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import Application, ManualReviewReason, ManualReviewStatus, ManualReviewTask
from app.models.handoff import (
    ACTIVE_HANDOFF_STATUSES,
    HandoffActorType,
    HandoffChallengeType,
    HandoffSessionEvent,
    HandoffSessionStatus,
    ManualHandoffSession,
)


_ALLOWED_REASON_TO_CHALLENGE = {
    ManualReviewReason.captcha_detected.value: HandoffChallengeType.captcha.value,
    ManualReviewReason.mfa_required.value: HandoffChallengeType.mfa.value,
    ManualReviewReason.login_required.value: HandoffChallengeType.login.value,
    ManualReviewReason.anti_bot_challenge.value: HandoffChallengeType.anti_bot.value,
}


class HandoffSessionError(ValueError):
    pass


class HandoffSessionExpired(HandoffSessionError):
    pass


class HandoffSessionConflict(HandoffSessionError):
    pass


class HandoffTokenInvalid(HandoffSessionError):
    pass


@dataclass
class IssuedHandoffSession:
    session: ManualHandoffSession
    resume_token: str


@dataclass
class ClaimedHandoffSession:
    session: ManualHandoffSession
    lease_token: str


def _now() -> datetime:
    return datetime.utcnow()


def _fernet() -> Fernet:
    settings = get_settings()
    secret = settings.handoff_encryption_key or settings.answer_vault_key or settings.secret_key
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_handoff_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_handoff_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def _secret_hash(value: str) -> str:
    settings = get_settings()
    key = (settings.handoff_token_pepper or settings.secret_key).encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_secret(value: str, expected_hash: Optional[str]) -> bool:
    if not value or not expected_hash:
        return False
    return hmac.compare_digest(_secret_hash(value), expected_hash)


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


def _event(
    db: Session,
    session: ManualHandoffSession,
    event_type: str,
    *,
    actor_type: HandoffActorType | str = HandoffActorType.system,
    payload: Optional[Dict[str, Any]] = None,
) -> HandoffSessionEvent:
    actor = actor_type.value if isinstance(actor_type, HandoffActorType) else str(actor_type)
    record = HandoffSessionEvent(
        handoff_session_id=session.id,
        application_id=session.application_id,
        event_type=event_type,
        actor_type=actor,
        payload=payload or {},
    )
    db.add(record)
    return record


def _expire_if_needed(db: Session, session: ManualHandoffSession, now: Optional[datetime] = None) -> None:
    current = now or _now()
    if session.status in ACTIVE_HANDOFF_STATUSES and session.expires_at <= current:
        session.status = HandoffSessionStatus.expired.value
        session.failure_reason = "The manual handoff session expired before completion."
        session.lock_version = (session.lock_version or 0) + 1
        _event(db, session, "handoff_expired", payload={"expires_at": session.expires_at.isoformat()})


def challenge_type_for_review(review: ManualReviewTask) -> str:
    challenge_type = _ALLOWED_REASON_TO_CHALLENGE.get(review.reason_code)
    if not challenge_type:
        raise HandoffSessionError(
            f"Manual review reason {review.reason_code!r} is not resumable."
        )
    return challenge_type


def issue_handoff_session(
    db: Session,
    application: Application,
    review: ManualReviewTask,
    *,
    browser_provider: str,
    browser_session_id: Optional[str] = None,
    browser_endpoint: Optional[str] = None,
    browser_node_id: Optional[str] = None,
    browser_process_id: Optional[int] = None,
    browser_profile_path: Optional[str] = None,
    active_page_hint: Optional[str] = None,
    current_url: Optional[str] = None,
    current_fingerprint: Optional[str] = None,
    storage_state_path: Optional[str] = None,
    storage_state_hash: Optional[str] = None,
    screenshot_path: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    ttl_minutes: Optional[int] = None,
) -> IssuedHandoffSession:
    if review.application_id != application.id:
        raise HandoffSessionError("Manual review does not belong to the application.")
    if review.status not in {ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value}:
        raise HandoffSessionConflict("Manual review is no longer active.")

    challenge_type = challenge_type_for_review(review)
    settings = get_settings()
    ttl = ttl_minutes or settings.handoff_session_ttl_minutes
    now = _now()
    expires_at = now + timedelta(minutes=max(1, min(ttl, settings.handoff_session_max_ttl_minutes)))
    idempotency_key = f"handoff:{application.id}:review:{review.id}:v1"

    existing = (
        db.query(ManualHandoffSession)
        .filter(ManualHandoffSession.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        _expire_if_needed(db, existing, now)
        if existing.status in ACTIVE_HANDOFF_STATUSES:
            token = decrypt_handoff_secret(existing.encrypted_resume_token)
            if not token:
                raise HandoffSessionConflict("Existing handoff token cannot be recovered safely.")
            return IssuedHandoffSession(existing, token)
        raise HandoffSessionConflict("A terminal handoff session already exists for this review.")

    token = _new_secret()
    session = ManualHandoffSession(
        application_id=application.id,
        manual_review_id=review.id,
        user_id=application.user_id,
        challenge_type=challenge_type,
        status=HandoffSessionStatus.awaiting_user.value,
        idempotency_key=idempotency_key,
        resume_token_hash=_secret_hash(token),
        encrypted_resume_token=encrypt_handoff_secret(token),
        resume_token_prefix=token[:10],
        browser_provider=browser_provider,
        browser_session_id=browser_session_id,
        encrypted_browser_endpoint=encrypt_handoff_secret(browser_endpoint),
        browser_node_id=browser_node_id,
        browser_process_id=browser_process_id,
        browser_profile_path=browser_profile_path,
        active_page_hint=active_page_hint,
        current_url=current_url,
        current_fingerprint=current_fingerprint,
        storage_state_path=storage_state_path,
        storage_state_hash=storage_state_hash,
        screenshot_path=screenshot_path,
        expires_at=expires_at,
        handoff_metadata=metadata or {},
    )
    db.add(session)
    db.flush()
    review.status = ManualReviewStatus.in_progress.value
    review.expires_at = expires_at
    # The legacy plaintext field is deliberately cleared.
    review.resume_token = None
    _event(
        db,
        session,
        "handoff_issued",
        payload={
            "challenge_type": challenge_type,
            "browser_provider": browser_provider,
            "expires_at": expires_at.isoformat(),
        },
    )
    return IssuedHandoffSession(session, token)


def claim_handoff_session(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
    resume_token: str,
) -> ClaimedHandoffSession:
    now = _now()
    _expire_if_needed(db, session, now)
    if session.user_id != user_id:
        raise HandoffTokenInvalid("Handoff session does not belong to the authenticated user.")
    if session.status == HandoffSessionStatus.expired.value:
        raise HandoffSessionExpired("Handoff session has expired.")
    if session.status != HandoffSessionStatus.awaiting_user.value:
        raise HandoffSessionConflict("Handoff session has already been claimed or completed.")
    if not _verify_secret(resume_token, session.resume_token_hash):
        raise HandoffTokenInvalid("Resume token is invalid.")

    lease_token = _new_secret()
    settings = get_settings()
    lease_expires_at = min(
        session.expires_at,
        now + timedelta(minutes=settings.handoff_lease_ttl_minutes),
    )
    session.status = HandoffSessionStatus.claimed.value
    session.resume_token_consumed_at = now
    session.claimed_at = now
    session.last_heartbeat_at = now
    session.lease_token_hash = _secret_hash(lease_token)
    session.encrypted_lease_token = encrypt_handoff_secret(lease_token)
    session.lease_expires_at = lease_expires_at
    session.lock_version = (session.lock_version or 0) + 1
    _event(
        db,
        session,
        "handoff_claimed",
        actor_type=HandoffActorType.user,
        payload={"lease_expires_at": lease_expires_at.isoformat()},
    )
    return ClaimedHandoffSession(session, lease_token)


def verify_handoff_lease(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
    lease_token: str,
    allowed_statuses: tuple[str, ...] = (HandoffSessionStatus.claimed.value,),
) -> None:
    now = _now()
    _expire_if_needed(db, session, now)
    if session.user_id != user_id:
        raise HandoffTokenInvalid("Handoff session does not belong to the authenticated user.")
    if session.status == HandoffSessionStatus.expired.value:
        raise HandoffSessionExpired("Handoff session has expired.")
    if session.status not in allowed_statuses:
        raise HandoffSessionConflict("Handoff session is not in an interactive state.")
    if not session.lease_expires_at or session.lease_expires_at <= now:
        raise HandoffSessionExpired("Interaction lease has expired.")
    if not _verify_secret(lease_token, session.lease_token_hash):
        raise HandoffTokenInvalid("Interaction lease token is invalid.")


def heartbeat_handoff_session(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
    lease_token: str,
) -> ManualHandoffSession:
    verify_handoff_lease(db, session, user_id=user_id, lease_token=lease_token)
    now = _now()
    settings = get_settings()
    session.last_heartbeat_at = now
    session.lease_expires_at = min(
        session.expires_at,
        now + timedelta(minutes=settings.handoff_lease_ttl_minutes),
    )
    session.lock_version = (session.lock_version or 0) + 1
    _event(
        db,
        session,
        "handoff_heartbeat",
        actor_type=HandoffActorType.user,
        payload={"lease_expires_at": session.lease_expires_at.isoformat()},
    )
    return session


def mark_handoff_ready(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
    lease_token: str,
    verification: Dict[str, Any],
) -> ManualHandoffSession:
    verify_handoff_lease(db, session, user_id=user_id, lease_token=lease_token)
    if not verification.get("challenge_cleared"):
        raise HandoffSessionConflict("Browser provider has not verified challenge completion.")
    now = _now()
    session.status = HandoffSessionStatus.ready_to_resume.value
    session.ready_at = now
    session.lease_token_hash = None
    session.encrypted_lease_token = None
    session.lease_expires_at = None
    session.lock_version = (session.lock_version or 0) + 1
    safe_verification = {
        key: value
        for key, value in verification.items()
        if key not in {"secret", "code", "password", "token", "response_value"}
    }
    _event(
        db,
        session,
        "handoff_ready_to_resume",
        actor_type=HandoffActorType.user,
        payload=safe_verification,
    )
    return session


def begin_handoff_resume(db: Session, session: ManualHandoffSession) -> ManualHandoffSession:
    now = _now()
    _expire_if_needed(db, session, now)
    if session.status == HandoffSessionStatus.resuming.value:
        return session
    if session.status != HandoffSessionStatus.ready_to_resume.value:
        raise HandoffSessionConflict("Handoff session is not ready to resume.")
    if session.resume_attempt_count >= session.max_resume_attempts:
        session.status = HandoffSessionStatus.failed.value
        session.failure_reason = "Maximum resume attempts exceeded."
        _event(db, session, "handoff_resume_attempts_exhausted", actor_type=HandoffActorType.worker)
        raise HandoffSessionConflict(session.failure_reason)
    session.status = HandoffSessionStatus.resuming.value
    session.resumed_at = now
    session.resume_attempt_count = (session.resume_attempt_count or 0) + 1
    session.lock_version = (session.lock_version or 0) + 1
    _event(
        db,
        session,
        "handoff_resume_started",
        actor_type=HandoffActorType.worker,
        payload={"attempt": session.resume_attempt_count},
    )
    return session


def complete_handoff_resume(
    db: Session,
    session: ManualHandoffSession,
    *,
    result: Optional[Dict[str, Any]] = None,
) -> ManualHandoffSession:
    if session.status == HandoffSessionStatus.completed.value:
        return session
    if session.status != HandoffSessionStatus.resuming.value:
        raise HandoffSessionConflict("Handoff session is not currently resuming.")
    session.status = HandoffSessionStatus.completed.value
    session.completed_at = _now()
    session.lock_version = (session.lock_version or 0) + 1
    _event(
        db,
        session,
        "handoff_resume_completed",
        actor_type=HandoffActorType.worker,
        payload=result or {},
    )
    return session


def fail_handoff_resume(
    db: Session,
    session: ManualHandoffSession,
    *,
    reason: str,
    retryable: bool,
) -> ManualHandoffSession:
    if retryable and session.resume_attempt_count < session.max_resume_attempts:
        session.status = HandoffSessionStatus.ready_to_resume.value
    else:
        session.status = HandoffSessionStatus.failed.value
    session.failure_reason = reason
    session.lock_version = (session.lock_version or 0) + 1
    _event(
        db,
        session,
        "handoff_resume_failed",
        actor_type=HandoffActorType.worker,
        payload={"reason": reason[:500], "retryable": retryable},
    )
    return session


def cancel_handoff_session(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
    reason: str = "Cancelled by user.",
) -> ManualHandoffSession:
    if session.user_id != user_id:
        raise HandoffTokenInvalid("Handoff session does not belong to the authenticated user.")
    if session.status in {
        HandoffSessionStatus.completed.value,
        HandoffSessionStatus.expired.value,
        HandoffSessionStatus.cancelled.value,
        HandoffSessionStatus.failed.value,
    }:
        return session
    session.status = HandoffSessionStatus.cancelled.value
    session.cancelled_at = _now()
    session.failure_reason = reason
    session.lease_token_hash = None
    session.encrypted_lease_token = None
    session.lease_expires_at = None
    session.lock_version = (session.lock_version or 0) + 1
    _event(
        db,
        session,
        "handoff_cancelled",
        actor_type=HandoffActorType.user,
        payload={"reason": reason[:500]},
    )
    return session
