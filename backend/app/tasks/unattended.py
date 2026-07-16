"""Second fail-closed chokepoint for scheduled application submissions."""

import logging
from datetime import datetime

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application, ApplicationStatus, ManualReviewReason
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.application_state import create_manual_review_task
from app.services.unattended_policy import evaluate_unattended_job_policy


logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.unattended.submit_unattended_application_task",
    queue="applications",
)
def submit_unattended_application_task(
    self,
    application_id: int,
    dry_run: bool = True,
):
    """Re-evaluate live policy immediately before the normal submit worker."""
    db = SessionLocal()
    try:
        app = (
            db.query(Application)
            .filter(Application.id == application_id)
            .with_for_update()
            .first()
        )
        if not app:
            return {"error": "Application not found"}
        job = db.query(Job).filter(Job.id == app.job_id).first()
        user = db.query(User).filter(User.id == app.user_id).first()
        if not job or not user:
            return {"error": "Missing job or user"}

        decision = evaluate_unattended_job_policy(db, user, job)
        if not decision.allowed:
            result = {
                "success": False,
                "dry_run": dry_run,
                "requires_manual_review": True,
                "error": decision.reason,
                "policy_decision": decision.to_dict(),
                "log": [
                    {
                        "action": "unattended_policy_blocked",
                        "reason_code": decision.code,
                        "reason": decision.reason,
                        "ts": datetime.utcnow().isoformat(),
                    }
                ],
            }
            app.status = ApplicationStatus.pending
            app.automation_log = result["log"]
            create_manual_review_task(
                db,
                app,
                ManualReviewReason.safety_gate_blocked,
                decision.reason,
                details={"unattended": True, **decision.to_dict()},
                blocking_url=job.url,
            )
            db.add(
                Notification(
                    user_id=user.id,
                    type=NotificationType.system,
                    title=f"Unattended action blocked: {job.title}",
                    message=decision.reason,
                    data={
                        "job_id": job.id,
                        "application_id": app.id,
                        "reason": decision.code,
                    },
                )
            )
            db.commit()
            logger.warning(
                "Blocked unattended application %s: %s",
                application_id,
                decision.code,
            )
            return result
    except Exception as exc:
        logger.exception("submit_unattended_application_task failed")
        db.rollback()
        raise self.retry(exc=exc, countdown=60, max_retries=2)
    finally:
        db.close()

    from app.tasks.applications import submit_application_task

    return submit_application_task.run(application_id, dry_run=dry_run)
