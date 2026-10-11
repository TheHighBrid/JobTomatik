"""JT5 worker entry point for durable reserved attempts."""
from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.application_attempt_lifecycle_jt5 import claim_jt5_attempt


@celery_app.task(name="app.tasks.jt5_execution.execute_reserved_application", queue="applications", max_retries=0)
def execute_reserved_application(application_id: int, attempt_reference: str):
    db = SessionLocal()
    try:
        attempt = claim_jt5_attempt(db, application_id, attempt_reference)
        if attempt is None:
            db.rollback()
            return {"status": "not_claimed", "idempotent": True}
        db.commit()
        return {"status": "claimed", "attempt_reference": attempt_reference}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
