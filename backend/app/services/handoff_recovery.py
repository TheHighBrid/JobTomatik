from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.handoff import HandoffActorType, HandoffSessionStatus, ManualHandoffSession
from app.services.handoff_session import (
    ClaimedHandoffSession,
    HandoffSessionConflict,
    HandoffSessionExpired,
    HandoffTokenInvalid,
    _event,
    _new_secret,
    _secret_hash,
    _setting,
    encrypt_handoff_secret,
)


def recover_handoff_lease(
    db: Session,
    session: ManualHandoffSession,
    *,
    user_id: int,
) -> ClaimedHandoffSession:
    """Rotate an expired interaction lease for the authenticated owner.

    An active lease cannot be displaced. Recovery exists only for refreshes,
    closed tabs, or interrupted clients after the previous lease has expired.
    """
    now = datetime.utcnow()
    if session.user_id != user_id:
        raise HandoffTokenInvalid("Handoff session does not belong to the authenticated user.")
    if session.expires_at <= now:
        session.status = HandoffSessionStatus.expired.value
        session.failure_reason = "The manual handoff session expired before lease recovery."
        _event(db, session, "handoff_expired", payload={"expires_at": session.expires_at.isoformat()})
        raise HandoffSessionExpired("Handoff session has expired.")
    if session.status != HandoffSessionStatus.claimed.value:
        raise HandoffSessionConflict("Only a claimed handoff session can recover its lease.")
    if session.lease_expires_at and session.lease_expires_at > now:
        raise HandoffSessionConflict("The existing interaction lease is still active.")

    lease_token = _new_secret()
    lease_minutes = int(_setting("handoff_lease_ttl_minutes", 5))
    session.lease_token_hash = _secret_hash(lease_token)
    session.encrypted_lease_token = encrypt_handoff_secret(lease_token)
    session.lease_expires_at = min(
        session.expires_at,
        now + timedelta(minutes=lease_minutes),
    )
    session.last_heartbeat_at = now
    session.lease_recovery_count = (session.lease_recovery_count or 0) + 1
    session.lock_version = (session.lock_version or 0) + 1
    _event(
        db,
        session,
        "handoff_lease_recovered",
        actor_type=HandoffActorType.user,
        payload={
            "lease_expires_at": session.lease_expires_at.isoformat(),
            "recovery_count": session.lease_recovery_count,
        },
    )
    return ClaimedHandoffSession(session=session, lease_token=lease_token)
