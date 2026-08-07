import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.application import Application, ApplicationEvent, FollowUp
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.email_service import send_email_with_receipt
from app.services.supervised_followup import (
    APPROVAL_ACTIVE,
    APPROVAL_UNAPPROVED,
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_NEEDS_RECIPIENT,
    STATUS_SENDING,
    STATUS_SENT,
    SupervisedFollowUpError,
    complete_followup_delivery,
    mark_followup_delivery_uncertain,
    reserve_followup_delivery,
)

logger = logging.getLogger(__name__)
settings = get_settings()
STALE_DELIVERY_RESERVATION = timedelta(minutes=15)


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _deliver_followup(followup_id: int) -> dict[str, Any]:
    """Reserve and deliver one exact approved follow-up.

    Reservation is committed before the external provider call. A worker crash after
    that point leaves the row in ``sending`` and therefore prevents an automatic
    duplicate. Any provider ambiguity becomes ``delivery_uncertain`` and consumes the
    approval so retry requires a new explicit user decision.
    """
    db = SessionLocal()
    try:
        followup = (
            db.query(FollowUp)
            .filter(FollowUp.id == followup_id)
            .with_for_update()
            .first()
        )
        if not followup:
            return {"followup_id": followup_id, "status": "not_found"}
        if followup.status == STATUS_SENT:
            return {
                "followup_id": followup.id,
                "status": STATUS_SENT,
                "idempotent": True,
                "duplicate_delivery_prevented": True,
            }
        if followup.status == STATUS_SENDING:
            return {
                "followup_id": followup.id,
                "status": STATUS_SENDING,
                "idempotent": True,
                "duplicate_delivery_prevented": True,
            }

        application = followup.application
        user = (
            db.query(User).filter(User.id == application.user_id).first()
            if application
            else None
        )
        if not application or not user:
            return {"followup_id": followup.id, "status": "blocked", "reason": "owner_missing"}

        try:
            preflight = reserve_followup_delivery(db, followup, user)
        except SupervisedFollowUpError as exc:
            # Persist any fail-closed expiry transition made during validation.
            db.commit()
            return {
                "followup_id": followup.id,
                "status": "blocked",
                "reason": str(exc),
                "delivery_attempted": False,
            }

        recipient = str(followup.recipient_email or "").strip()
        subject = str(followup.subject or "")
        message = str(followup.message or "")
        approval_reference = followup.approval_reference
        payload_hash = preflight["payload_hash"]
        db.commit()

        receipt = _run_async(
            send_email_with_receipt(
                to=recipient,
                subject=subject,
                body=message,
                require_provider=True,
            )
        )

        followup = (
            db.query(FollowUp)
            .filter(FollowUp.id == followup_id)
            .with_for_update()
            .first()
        )
        if not followup:
            return {"followup_id": followup_id, "status": "delivery_uncertain"}
        if followup.status != STATUS_SENDING:
            mark_followup_delivery_uncertain(
                db,
                followup,
                reason="Follow-up reservation state changed during provider delivery",
            )
            db.commit()
            return {
                "followup_id": followup.id,
                "status": followup.status,
                "delivery_uncertain": True,
            }

        if receipt.get("accepted"):
            complete_followup_delivery(
                db,
                followup,
                user,
                provider_status=receipt.get("status_code"),
                provider_message_id=receipt.get("message_id"),
            )
            db.commit()
            return {
                "followup_id": followup.id,
                "status": STATUS_SENT,
                "approval_reference": approval_reference,
                "payload_hash": payload_hash,
                "provider_status": receipt.get("status_code"),
                "provider_message_id": receipt.get("message_id"),
                "delivery_attempted": True,
            }

        reason = receipt.get("error") or (
            f"Email provider did not accept delivery (status={receipt.get('status_code')})"
        )
        mark_followup_delivery_uncertain(db, followup, reason=str(reason))
        db.commit()
        return {
            "followup_id": followup.id,
            "status": followup.status,
            "delivery_uncertain": True,
            "automatic_retry_allowed": False,
            "provider_status": receipt.get("status_code"),
        }
    except Exception as exc:
        logger.exception("Supervised follow-up delivery failed for %s", followup_id)
        db.rollback()
        try:
            followup = (
                db.query(FollowUp)
                .filter(FollowUp.id == followup_id)
                .with_for_update()
                .first()
            )
            if followup and followup.status == STATUS_SENDING:
                mark_followup_delivery_uncertain(
                    db,
                    followup,
                    reason=f"{type(exc).__name__}: {str(exc)[:250]}",
                )
                db.commit()
        except Exception:
            logger.exception("Could not persist uncertain follow-up delivery state")
            db.rollback()
        return {
            "followup_id": followup_id,
            "status": "delivery_uncertain",
            "automatic_retry_allowed": False,
            "error": f"{type(exc).__name__}: {str(exc)[:250]}",
        }
    finally:
        db.close()


def _recover_stale_followup_deliveries() -> dict[str, Any]:
    """Convert abandoned sending reservations into visible uncertain outcomes.

    A hard process death cannot safely tell whether SendGrid accepted the request.
    Once a reservation has been abandoned for 15 minutes, consume its approval and
    require operator review instead of retrying the provider call.
    """
    db = SessionLocal()
    recovered: list[int] = []
    try:
        cutoff = datetime.now(timezone.utc) - STALE_DELIVERY_RESERVATION
        candidate_ids = [
            row[0]
            for row in db.query(FollowUp.id)
            .filter(
                FollowUp.status == STATUS_SENDING,
                FollowUp.last_send_attempt_at.isnot(None),
                FollowUp.last_send_attempt_at <= cutoff,
            )
            .all()
        ]
        for followup_id in candidate_ids:
            followup = (
                db.query(FollowUp)
                .filter(
                    FollowUp.id == followup_id,
                    FollowUp.status == STATUS_SENDING,
                    FollowUp.last_send_attempt_at.isnot(None),
                    FollowUp.last_send_attempt_at <= cutoff,
                )
                .with_for_update()
                .first()
            )
            if not followup:
                continue
            mark_followup_delivery_uncertain(
                db,
                followup,
                reason=(
                    "Delivery reservation exceeded 15 minutes without a recorded provider outcome; "
                    "automatic retry remains disabled."
                ),
            )
            recovered.append(followup.id)
        db.commit()
        return {
            "checked": len(candidate_ids),
            "recovered": len(recovered),
            "followup_ids": recovered,
            "automatic_retry_allowed": False,
        }
    except Exception as exc:
        logger.exception("Stale follow-up reservation recovery failed")
        db.rollback()
        return {
            "checked": 0,
            "recovered": 0,
            "followup_ids": [],
            "automatic_retry_allowed": False,
            "error": f"{type(exc).__name__}: {str(exc)[:250]}",
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.followup.send_followup", queue="followup")
def send_followup(followup_id: int):
    return _deliver_followup(followup_id)


@celery_app.task(name="app.tasks.followup.recover_stale_followup_deliveries", queue="followup")
def recover_stale_followup_deliveries():
    return _recover_stale_followup_deliveries()


@celery_app.task(name="app.tasks.followup.send_pending_followups", queue="followup")
def send_pending_followups():
    """Deliver only due follow-ups with active exact-payload approval."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_ids = [
            row[0]
            for row in db.query(FollowUp.id)
            .filter(
                FollowUp.status == STATUS_APPROVED,
                FollowUp.approval_status == APPROVAL_ACTIVE,
                FollowUp.scheduled_at <= now,
            )
            .all()
        ]
    finally:
        db.close()

    results = [_deliver_followup(followup_id) for followup_id in due_ids]
    return {
        "checked": len(due_ids),
        "sent": sum(1 for result in results if result.get("status") == STATUS_SENT),
        "results": results,
    }


@celery_app.task(name="app.tasks.followup.schedule_auto_followup", queue="followup")
def schedule_auto_followup(application_id: int, days_after: int = 7):
    """Prepare a follow-up draft/reminder. Never select a recipient or authorize send."""
    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app or not app.applied_at:
            return {"error": "Application not found or not yet applied"}

        user = db.query(User).filter(User.id == app.user_id).first()
        job = app.job
        if not user:
            return {"error": "Application user not found"}

        existing = (
            db.query(FollowUp)
            .filter(
                FollowUp.application_id == application_id,
                FollowUp.status.notin_([STATUS_SENT, STATUS_CANCELLED]),
            )
            .all()
        )
        for item in existing:
            if dict(item.delivery_metadata or {}).get("source") == "auto_followup_draft":
                return {
                    "followup_id": item.id,
                    "scheduled_at": item.scheduled_at.isoformat(),
                    "status": item.status,
                    "idempotent": True,
                    "outreach_authorized": False,
                }

        bounded_days = max(1, min(int(days_after), settings.supervised_followup_max_schedule_days))
        scheduled = app.applied_at + timedelta(days=bounded_days)
        title = job.title if job else "the position"
        company = job.company if job else "the company"
        applicant_name = user.full_name or user.email
        subject = f"Following up on my {title} application at {company}"
        message = (
            f"Dear Hiring Team,\n\n"
            f"I’m following up on my application for the {title} position at {company}. "
            f"I remain interested in the opportunity and would appreciate any update on next steps.\n\n"
            f"Please let me know if I can provide any additional information.\n\n"
            f"Best regards,\n{applicant_name}"
        )
        followup = FollowUp(
            application_id=application_id,
            scheduled_at=scheduled,
            subject=subject,
            message=message,
            recipient_email=None,
            recruiter_contact_id=None,
            status=STATUS_NEEDS_RECIPIENT,
            approval_status=APPROVAL_UNAPPROVED,
            delivery_metadata={
                "source": "auto_followup_draft",
                "prepared_at": datetime.now(timezone.utc).isoformat(),
                "outreach_authorized": False,
                "recipient_selected": False,
            },
        )
        db.add(followup)
        db.flush()
        db.add(
            ApplicationEvent(
                application_id=app.id,
                event_type="followup_draft_prepared",
                from_state=app.automation_state,
                to_state=app.automation_state,
                payload={
                    "followup_id": followup.id,
                    "scheduled_at": scheduled.isoformat(),
                    "outreach_authorized": False,
                    "recipient_selected": False,
                },
            )
        )
        db.add(
            Notification(
                user_id=app.user_id,
                type=NotificationType.system,
                title=f"Follow-up draft ready: {title}",
                message="Choose the exact recruiter recipient and approve the message before anything can be sent.",
                data={"application_id": app.id, "followup_id": followup.id},
            )
        )
        db.commit()
        return {
            "followup_id": followup.id,
            "scheduled_at": scheduled.isoformat(),
            "status": followup.status,
            "recipient_email": None,
            "outreach_authorized": False,
            "delivery_attempted": False,
        }
    except Exception as exc:
        logger.exception("schedule_auto_followup failed")
        db.rollback()
        return {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    finally:
        db.close()
