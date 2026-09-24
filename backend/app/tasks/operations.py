import logging

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.user import User
from app.services.application_recovery import recover_stale_application_attempts
from app.services.operational_observability import sync_operational_notifications
from app.services.operator_submission_reconciler import reconcile_operator_submissions

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.operations.refresh_adapter_health_alerts", queue="followup")
def refresh_adapter_health_alerts():
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        results = [sync_operational_notifications(db, user.id) for user in users]
        db.commit()
        return {
            "users_checked": len(users),
            "alerts_detected": sum(item["incidents_detected"] for item in results),
            "incidents_detected": sum(item["incidents_detected"] for item in results),
            "notifications_created": sum(item["notifications_created"] for item in results),
            "notifications_deduplicated": sum(item["notifications_deduplicated"] for item in results),
            "digests_created": sum(1 for item in results if item["digest_created"]),
            "users": results,
        }
    except Exception:
        db.rollback()
        logger.exception("refresh_adapter_health_alerts failed")
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.operations.recover_stale_application_attempts", queue="followup")
def recover_stale_application_attempts_task():
    db = SessionLocal()
    try:
        result = recover_stale_application_attempts(db)
        db.commit()
        if result["recovered"]:
            logger.warning("Recovered %s stale application attempt(s)", result["recovered"])
        return result
    except Exception:
        db.rollback()
        logger.exception("recover_stale_application_attempts failed")
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.operations.reconcile_operator_submissions", queue="applications")
def reconcile_operator_submissions_task():
    """Observe retained confirmation pages after a human final click and close state."""
    db = SessionLocal()
    try:
        result = reconcile_operator_submissions(db)
        db.commit()
        if result["confirmed"]:
            logger.info("Reconciled %s human-confirmed application(s)", result["confirmed"])
        return result
    except Exception:
        db.rollback()
        logger.exception("reconcile_operator_submissions failed")
        raise
    finally:
        db.close()


from app.tasks import agent_execution as _agent_execution_tasks  # noqa: E402,F401
