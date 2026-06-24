import asyncio
import logging
from datetime import datetime, timedelta
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application, ApplicationStatus, FollowUp
from app.models.user import User
from app.models.notification import Notification, NotificationType
from app.services.email_service import send_followup_email

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.followup.send_pending_followups", queue="followup")
def send_pending_followups():
    """Check all pending follow-ups and send those that are due."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due = (
            db.query(FollowUp)
            .filter(
                FollowUp.status == "pending",
                FollowUp.scheduled_at <= now,
            )
            .all()
        )

        sent_count = 0
        for followup in due:
            app = followup.application
            if not app or not followup.recipient_email:
                followup.status = "skipped"
                continue

            user = db.query(User).filter(User.id == app.user_id).first()
            if not user:
                continue

            job = app.job
            days_ago = (now - app.applied_at).days if app.applied_at else 7

            success = asyncio.get_event_loop().run_until_complete(
                send_followup_email(
                    to=followup.recipient_email,
                    applicant_name=user.full_name or user.email,
                    job_title=job.title if job else "the position",
                    company=job.company if job else "your company",
                    applied_days_ago=days_ago,
                    custom_message=followup.message,
                )
            )

            followup.sent_at = now
            followup.status = "sent" if success else "failed"

            if success:
                sent_count += 1
                db.add(Notification(
                    user_id=app.user_id,
                    type=NotificationType.followup_sent,
                    title=f"Follow-up sent for {job.title if job else 'application'}",
                    message=f"Your follow-up email to {followup.recipient_email} was sent.",
                    data={"application_id": app.id, "followup_id": followup.id},
                ))

        db.commit()
        return {"sent": sent_count, "checked": len(due)}
    except Exception as e:
        logger.exception("send_pending_followups failed")
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.followup.schedule_auto_followup", queue="followup")
def schedule_auto_followup(application_id: int, days_after: int = 7):
    """Auto-schedule a follow-up email N days after application."""
    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app or not app.applied_at:
            return {"error": "Application not found or not yet applied"}

        user = db.query(User).filter(User.id == app.user_id).first()
        job = app.job

        scheduled = app.applied_at + timedelta(days=days_after)
        followup = FollowUp(
            application_id=application_id,
            scheduled_at=scheduled,
            subject=f"Following up on my {job.title if job else 'application'} application",
            message=None,
            recipient_email=user.email,
            status="pending",
        )
        db.add(followup)
        db.commit()
        return {"followup_id": followup.id, "scheduled_at": scheduled.isoformat()}
    except Exception as e:
        logger.exception("schedule_auto_followup failed")
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
