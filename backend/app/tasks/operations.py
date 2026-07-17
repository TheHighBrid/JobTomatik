import logging

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.user import User
from app.services.adapter_health_notifications import sync_adapter_health_notifications
from app.services.application_recovery import recover_stale_application_attempts


logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.operations.refresh_adapter_health_alerts",
    queue="followup",
)
def refresh_adapter_health_alerts():
    """Refresh deduplicated adapter-health notifications for active users."""

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        results = []
        for user in users:
            results.append(sync_adapter_health_notifications(db, user.id))
        db.commit()
        return {
            "users_checked": len(users),
            "alerts_detected": sum(item["alerts_detected"] for item in results),
            "notifications_created": sum(
                item["notifications_created"] for item in results
            ),
            "notifications_deduplicated": sum(
                item["notifications_deduplicated"] for item in results
            ),
            "users": results,
        }
    except Exception:
        db.rollback()
        logger.exception("refresh_adapter_health_alerts failed")
        raise
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.operations.recover_stale_application_attempts",
    queue="followup",
)
def recover_stale_application_attempts_task():
    """Move abandoned applying rows to explicit fail-closed review states."""

    db = SessionLocal()
    try:
        result = recover_stale_application_attempts(db)
        db.commit()
        if result["recovered"]:
            logger.warning(
                "Recovered %s stale application attempt(s)",
                result["recovered"],
            )
        return result
    except Exception:
        db.rollback()
        logger.exception("recover_stale_application_attempts failed")
        raise
    finally:
        db.close()
