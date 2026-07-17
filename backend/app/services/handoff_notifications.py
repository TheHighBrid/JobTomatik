"""Idempotent, secret-free notifications for resumable manual handoffs."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.application import Application, ManualReviewTask
from app.models.handoff import ManualHandoffSession
from app.models.notification import Notification, NotificationType


HANDOFF_REQUIRED_KIND = "manual_handoff_required"

_CHALLENGE_LABELS = {
    "captcha": "Human verification",
    "anti_bot": "Anti-bot verification",
    "mfa": "Multi-factor authentication",
    "login": "Account sign-in",
}


def _notification_key(session: ManualHandoffSession) -> str:
    return f"handoff:{session.public_id}:required:v1"


def _existing_notification(
    db: Session,
    *,
    user_id: int,
    notification_key: str,
) -> Optional[Notification]:
    candidates = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.type == NotificationType.system,
        )
        .order_by(Notification.id.desc())
        .all()
    )
    for notification in candidates:
        data = notification.data if isinstance(notification.data, dict) else {}
        if data.get("notification_key") == notification_key:
            return notification
    return None


def create_handoff_required_notification(
    db: Session,
    application: Application,
    review: ManualReviewTask,
    session: ManualHandoffSession,
) -> Notification:
    """Create one actionable notification without persisting any handoff secret."""
    notification_key = _notification_key(session)
    existing = _existing_notification(
        db,
        user_id=application.user_id,
        notification_key=notification_key,
    )
    if existing:
        return existing

    challenge_label = _CHALLENGE_LABELS.get(
        str(session.challenge_type or "").lower(),
        "Manual action",
    )
    expires_at = session.expires_at.isoformat()
    blocking_url = review.blocking_url or session.current_url or ""
    notification = Notification(
        user_id=application.user_id,
        type=NotificationType.system,
        title="Action required to continue an application",
        message=(
            f"{challenge_label} is blocking this application. "
            f"Complete the secure handoff before {expires_at}."
        ),
        data={
            "notification_key": notification_key,
            "kind": HANDOFF_REQUIRED_KIND,
            "application_id": application.id,
            "job_id": application.job_id,
            "manual_review_id": review.id,
            "handoff_public_id": session.public_id,
            "handoff_status": session.status,
            "challenge_type": session.challenge_type,
            "blocking_url": blocking_url,
            "expires_at": expires_at,
            "screenshot_available": bool(session.screenshot_path),
        },
    )
    db.add(notification)
    db.flush()
    return notification


__all__ = [
    "HANDOFF_REQUIRED_KIND",
    "create_handoff_required_notification",
]
