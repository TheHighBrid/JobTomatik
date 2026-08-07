"""Supervised recruiter follow-up approval and delivery state.

A follow-up approval is independent from application-submission approval. Every
outbound email is bound to one user-owned recruiter contact, exact recipient,
subject, message, schedule, application, and one-time send idempotency key.
Mutating any bound field invalidates approval and prevents delivery.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import Application, ApplicationEvent, ApplicationStatus, FollowUp
from app.models.intelligence import RecruiterContact, RecruiterInteraction
from app.models.notification import Notification, NotificationType
from app.models.user import User


settings = get_settings()

APPROVAL_UNAPPROVED = "unapproved"
APPROVAL_ACTIVE = "active"
APPROVAL_REVOKED = "revoked"
APPROVAL_CONSUMED = "consumed"
APPROVAL_EXPIRED = "expired"

STATUS_DRAFT = "draft"
STATUS_NEEDS_RECIPIENT = "needs_recipient"
STATUS_APPROVED = "approved"
STATUS_SENDING = "sending"
STATUS_SENT = "sent"
STATUS_DELIVERY_UNCERTAIN = "delivery_uncertain"
STATUS_CANCELLED = "cancelled"

CLOSED_STATUSES = {STATUS_SENT, STATUS_CANCELLED, STATUS_DELIVERY_UNCERTAIN}
FOLLOWUP_ELIGIBLE_APPLICATION_STATUSES = {
    ApplicationStatus.applied.value,
    ApplicationStatus.interviewing.value,
}
APPROVAL_STATE_BLOCKERS = {"followup_approval_expired", "followup_payload_drifted"}


class SupervisedFollowUpError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize SQLite-naive and PostgreSQL-aware timestamps to one UTC form."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _hash_text(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def _normalized_company(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def approval_acknowledgment(followup: FollowUp) -> str:
    recipient = _normalized_email(followup.recipient_email)
    return f"APPROVE FOLLOWUP {followup.id} TO {recipient}"


def _application_status_value(application: Application) -> str:
    value = application.status
    return str(value.value if hasattr(value, "value") else value)


def _bound_payload(
    followup: FollowUp,
    application: Application,
    contact: RecruiterContact | None,
) -> dict[str, Any]:
    job = application.job
    scheduled_at = _as_utc(followup.scheduled_at)
    scheduled = scheduled_at.isoformat() if scheduled_at else None
    return {
        "followup_id": followup.id,
        "application_id": application.id,
        "user_id": application.user_id,
        "job_id": application.job_id,
        "job_company": str(job.company or "").strip() if job else "",
        "job_title": str(job.title or "").strip() if job else "",
        "recruiter_contact_id": followup.recruiter_contact_id,
        "recruiter_contact_email": _normalized_email(contact.email) if contact else "",
        "recipient_email": _normalized_email(followup.recipient_email),
        "subject": followup.subject or "",
        "message": followup.message or "",
        "scheduled_at": scheduled,
        "send_idempotency_key": followup.send_idempotency_key,
    }


def _owned_contact(
    db: Session,
    *,
    user_id: int,
    contact_id: int | None,
) -> RecruiterContact | None:
    if not contact_id:
        return None
    return (
        db.query(RecruiterContact)
        .filter(
            RecruiterContact.id == contact_id,
            RecruiterContact.user_id == user_id,
        )
        .first()
    )


def current_payload_hash(
    db: Session,
    followup: FollowUp,
    user: User,
) -> tuple[str | None, RecruiterContact | None]:
    application = followup.application
    if not application or application.user_id != user.id:
        return None, None
    contact = _owned_contact(
        db,
        user_id=user.id,
        contact_id=followup.recruiter_contact_id,
    )
    return _hash(_bound_payload(followup, application, contact)), contact


def build_followup_preflight(
    db: Session,
    followup: FollowUp,
    user: User,
) -> dict[str, Any]:
    application = followup.application
    blockers: list[str] = []
    contact: RecruiterContact | None = None

    if not application or application.user_id != user.id:
        blockers.append("owned_application_missing")
    else:
        app_status = _application_status_value(application)
        if app_status not in FOLLOWUP_ELIGIBLE_APPLICATION_STATUSES:
            blockers.append("application_not_followup_eligible")
        if not application.applied_at:
            blockers.append("application_applied_timestamp_missing")

    recipient = _normalized_email(followup.recipient_email)
    if not recipient:
        blockers.append("recipient_email_missing")
    if recipient and recipient == _normalized_email(user.email):
        blockers.append("recipient_is_applicant_email")

    if application:
        contact = _owned_contact(
            db,
            user_id=user.id,
            contact_id=followup.recruiter_contact_id,
        )
        if followup.recruiter_contact_id and contact is None:
            blockers.append("recruiter_contact_not_owned")
        elif not followup.recruiter_contact_id:
            blockers.append("recruiter_contact_required")
        elif not _normalized_email(contact.email):
            blockers.append("recruiter_contact_email_missing")
        elif _normalized_email(contact.email) != recipient:
            blockers.append("recruiter_contact_email_mismatch")

        job = application.job
        if contact and job and _normalized_company(contact.company) != _normalized_company(job.company):
            blockers.append("recruiter_company_mismatch")

    if not (followup.subject or "").strip():
        blockers.append("subject_missing")
    if not (followup.message or "").strip():
        blockers.append("message_missing")
    if not followup.send_idempotency_key:
        blockers.append("send_idempotency_key_missing")
    if followup.status in CLOSED_STATUSES:
        blockers.append("followup_closed")

    now = utcnow()
    scheduled_at = _as_utc(followup.scheduled_at)
    if not scheduled_at:
        blockers.append("scheduled_at_missing")
    elif scheduled_at > now + timedelta(days=settings.supervised_followup_max_schedule_days):
        blockers.append("scheduled_too_far_in_future")

    payload_hash = None
    if application:
        payload_hash = _hash(_bound_payload(followup, application, contact))

    approval_expired = False
    approval_expires_at = _as_utc(followup.approval_expires_at)
    if followup.approval_status == APPROVAL_ACTIVE and approval_expires_at:
        if approval_expires_at <= now:
            approval_expired = True
            blockers.append("followup_approval_expired")
    payload_drifted = bool(
        followup.approval_status == APPROVAL_ACTIVE
        and followup.approval_payload_hash
        and payload_hash
        and followup.approval_payload_hash != payload_hash
    )
    if payload_drifted:
        blockers.append("followup_payload_drifted")

    blockers = list(dict.fromkeys(blockers))
    hard_blockers = [item for item in blockers if item not in APPROVAL_STATE_BLOCKERS]
    approval_active = bool(
        followup.approval_status == APPROVAL_ACTIVE
        and not approval_expired
        and not payload_drifted
        and payload_hash
        and followup.approval_payload_hash == payload_hash
    )
    due = bool(scheduled_at and scheduled_at <= now)
    provider_configured = bool(settings.sendgrid_api_key)
    global_send_enabled = bool(settings.allow_real_followup_send)

    return {
        "followup_id": followup.id,
        "application_id": application.id if application else None,
        "status": followup.status,
        "approval_status": followup.approval_status,
        "approval_reference": followup.approval_reference,
        "approval_active": approval_active,
        "approval_expires_at": approval_expires_at.isoformat() if approval_expires_at else None,
        "eligible_for_approval": not hard_blockers,
        "ready_for_delivery": bool(
            approval_active
            and not hard_blockers
            and due
            and provider_configured
            and global_send_enabled
            and followup.status == STATUS_APPROVED
        ),
        "blockers": blockers,
        "payload_hash": payload_hash,
        "payload_drifted": payload_drifted,
        "recipient_email": recipient or None,
        "recipient_hash": _hash_text(recipient) if recipient else None,
        "recruiter_contact_id": followup.recruiter_contact_id,
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        "due": due,
        "provider_configured": provider_configured,
        "global_send_enabled": global_send_enabled,
        "expected_acknowledgment": approval_acknowledgment(followup),
        "send_idempotency_key": followup.send_idempotency_key,
        "send_attempt_count": int(followup.send_attempt_count or 0),
        "last_send_attempt_at": (
            _as_utc(followup.last_send_attempt_at).isoformat()
            if followup.last_send_attempt_at
            else None
        ),
        "sent_at": _as_utc(followup.sent_at).isoformat() if followup.sent_at else None,
        "delivery_metadata": dict(followup.delivery_metadata or {}),
    }


def revoke_followup_approval(
    db: Session,
    followup: FollowUp,
    *,
    reason: str,
    user_id: int | None = None,
) -> None:
    if followup.approval_status == APPROVAL_ACTIVE:
        followup.approval_status = APPROVAL_REVOKED
        followup.status = STATUS_DRAFT if followup.recipient_email else STATUS_NEEDS_RECIPIENT
        application = followup.application
        if application:
            db.add(
                ApplicationEvent(
                    application_id=application.id,
                    event_type="supervised_followup_approval_revoked",
                    from_state=application.automation_state,
                    to_state=application.automation_state,
                    payload={
                        "followup_id": followup.id,
                        "approval_reference": followup.approval_reference,
                        "payload_hash": followup.approval_payload_hash,
                        "reason": reason[:200],
                        "revoked_by_user_id": user_id,
                    },
                )
            )


def reset_followup_after_mutation(
    db: Session,
    followup: FollowUp,
    *,
    reason: str,
    user_id: int,
) -> None:
    revoke_followup_approval(db, followup, reason=reason, user_id=user_id)
    followup.payload_hash = None
    followup.approval_payload_hash = None
    followup.approved_at = None
    followup.approval_expires_at = None
    followup.approved_by_user_id = None
    if followup.status not in CLOSED_STATUSES:
        followup.status = STATUS_DRAFT if followup.recipient_email else STATUS_NEEDS_RECIPIENT
        followup.approval_status = APPROVAL_UNAPPROVED


def approve_followup(
    db: Session,
    followup: FollowUp,
    user: User,
    *,
    acknowledgment: str,
) -> dict[str, Any]:
    preflight = build_followup_preflight(db, followup, user)
    hard_blockers = [
        item for item in preflight["blockers"] if item not in APPROVAL_STATE_BLOCKERS
    ]
    if hard_blockers:
        raise SupervisedFollowUpError(
            "Follow-up approval is blocked: " + ", ".join(hard_blockers)
        )
    expected = approval_acknowledgment(followup)
    if acknowledgment.strip() != expected:
        raise SupervisedFollowUpError(
            f"Exact follow-up acknowledgment required: {expected}"
        )

    now = utcnow()
    scheduled_anchor = max(_as_utc(followup.scheduled_at) or now, now)
    expires_at = min(
        scheduled_anchor + timedelta(days=1),
        now + timedelta(days=settings.supervised_followup_max_schedule_days),
    )
    payload_hash = preflight["payload_hash"]
    followup.payload_hash = payload_hash
    followup.approval_payload_hash = payload_hash
    followup.approval_reference = str(uuid4())
    followup.approval_status = APPROVAL_ACTIVE
    followup.approved_at = now
    followup.approval_expires_at = expires_at
    followup.approved_by_user_id = user.id
    followup.status = STATUS_APPROVED

    application = followup.application
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="supervised_followup_approved",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "followup_id": followup.id,
                "approval_reference": followup.approval_reference,
                "payload_hash": payload_hash,
                "recipient_hash": preflight["recipient_hash"],
                "recruiter_contact_id": followup.recruiter_contact_id,
                "scheduled_at": preflight["scheduled_at"],
                "send_idempotency_key": followup.send_idempotency_key,
                "outreach_authorized": True,
                "application_submission_authorized": False,
            },
        )
    )
    db.flush()
    return build_followup_preflight(db, followup, user)


def validate_followup_for_delivery(
    db: Session,
    followup: FollowUp,
    user: User,
) -> dict[str, Any]:
    preflight = build_followup_preflight(db, followup, user)
    approval_expires_at = _as_utc(followup.approval_expires_at)
    if followup.approval_status == APPROVAL_ACTIVE and approval_expires_at:
        if approval_expires_at <= utcnow():
            followup.approval_status = APPROVAL_EXPIRED
            followup.status = STATUS_DRAFT
            db.flush()
            raise SupervisedFollowUpError("Follow-up approval expired")
    hard_blockers = [
        item for item in preflight["blockers"] if item not in APPROVAL_STATE_BLOCKERS
    ]
    if hard_blockers:
        raise SupervisedFollowUpError(
            "Follow-up delivery is blocked: " + ", ".join(hard_blockers)
        )
    if not preflight["approval_active"]:
        raise SupervisedFollowUpError("Follow-up does not have an active exact-payload approval")
    if not preflight["due"]:
        raise SupervisedFollowUpError("Follow-up is not due yet")
    if not settings.allow_real_followup_send:
        raise SupervisedFollowUpError("Real recruiter follow-up sending is disabled")
    if not settings.sendgrid_api_key:
        raise SupervisedFollowUpError("SENDGRID_API_KEY is required for real follow-up delivery")
    if followup.status != STATUS_APPROVED:
        raise SupervisedFollowUpError(f"Follow-up status is not deliverable: {followup.status}")
    return preflight


def reserve_followup_delivery(
    db: Session,
    followup: FollowUp,
    user: User,
) -> dict[str, Any]:
    """Atomically claim one approved payload for provider delivery.

    PostgreSQL row locks already serialize the surrounding worker path, but SQLite
    ignores ``FOR UPDATE``. The conditional UPDATE is therefore authoritative: only
    one process can move this exact approved payload from ``approved`` to ``sending``.
    """
    preflight = validate_followup_for_delivery(db, followup, user)
    now = utcnow()
    reserved = (
        db.query(FollowUp)
        .filter(
            FollowUp.id == followup.id,
            FollowUp.status == STATUS_APPROVED,
            FollowUp.approval_status == APPROVAL_ACTIVE,
            FollowUp.approval_payload_hash == preflight["payload_hash"],
        )
        .update(
            {
                FollowUp.status: STATUS_SENDING,
                FollowUp.send_attempt_count: func.coalesce(FollowUp.send_attempt_count, 0) + 1,
                FollowUp.last_send_attempt_at: now,
            },
            synchronize_session=False,
        )
    )
    if reserved != 1:
        db.expire_all()
        raise SupervisedFollowUpError(
            "Follow-up delivery reservation was already claimed or the approved payload changed"
        )

    db.flush()
    db.refresh(followup)
    followup.delivery_metadata = {
        **dict(followup.delivery_metadata or {}),
        "reservation": {
            "reserved_at": _as_utc(followup.last_send_attempt_at).isoformat(),
            "payload_hash": preflight["payload_hash"],
            "approval_reference": followup.approval_reference,
            "send_idempotency_key": followup.send_idempotency_key,
        },
    }
    db.flush()
    return preflight


def complete_followup_delivery(
    db: Session,
    followup: FollowUp,
    user: User,
    *,
    provider_status: int | None,
    provider_message_id: str | None,
) -> None:
    now = utcnow()
    followup.status = STATUS_SENT
    followup.sent_at = now
    followup.approval_status = APPROVAL_CONSUMED
    followup.delivery_metadata = {
        **dict(followup.delivery_metadata or {}),
        "delivery": {
            "accepted": True,
            "provider": "sendgrid",
            "provider_status": provider_status,
            "provider_message_id": provider_message_id,
            "delivered_at": now.isoformat(),
            "payload_hash": followup.approval_payload_hash,
        },
    }

    contact = _owned_contact(
        db,
        user_id=user.id,
        contact_id=followup.recruiter_contact_id,
    )
    if contact:
        contact.last_contacted_at = now
        next_followup_at = _as_utc(contact.next_followup_at)
        if next_followup_at and next_followup_at <= now:
            contact.next_followup_at = None
        db.add(
            RecruiterInteraction(
                contact_id=contact.id,
                application_id=followup.application_id,
                direction="outbound",
                channel="email",
                interaction_type="approved_followup",
                summary="Approved application follow-up email sent.",
                occurred_at=now,
                interaction_metadata={
                    "followup_id": followup.id,
                    "approval_reference": followup.approval_reference,
                    "payload_hash": followup.approval_payload_hash,
                    "send_idempotency_key": followup.send_idempotency_key,
                    "provider_message_id": provider_message_id,
                },
            )
        )

    application = followup.application
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="supervised_followup_sent",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "followup_id": followup.id,
                "approval_reference": followup.approval_reference,
                "payload_hash": followup.approval_payload_hash,
                "send_idempotency_key": followup.send_idempotency_key,
                "provider_status": provider_status,
                "provider_message_id": provider_message_id,
            },
        )
    )
    db.add(
        Notification(
            user_id=user.id,
            type=NotificationType.followup_sent,
            title=f"Follow-up sent for {application.job.title if application.job else 'application'}",
            message="Your explicitly approved recruiter follow-up was accepted by the email provider.",
            data={"application_id": application.id, "followup_id": followup.id},
        )
    )
    db.flush()


def mark_followup_delivery_uncertain(
    db: Session,
    followup: FollowUp,
    *,
    reason: str,
) -> None:
    followup.status = STATUS_DELIVERY_UNCERTAIN
    followup.approval_status = APPROVAL_CONSUMED
    followup.delivery_metadata = {
        **dict(followup.delivery_metadata or {}),
        "delivery": {
            "accepted": False,
            "uncertain": True,
            "reason": reason[:300],
            "recorded_at": utcnow().isoformat(),
            "payload_hash": followup.approval_payload_hash,
        },
    }
    application = followup.application
    if application:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="supervised_followup_delivery_uncertain",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "followup_id": followup.id,
                    "approval_reference": followup.approval_reference,
                    "payload_hash": followup.approval_payload_hash,
                    "send_idempotency_key": followup.send_idempotency_key,
                    "automatic_retry_allowed": False,
                },
            )
        )
    db.flush()
