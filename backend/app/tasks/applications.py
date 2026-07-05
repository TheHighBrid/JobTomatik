import asyncio
import logging
from datetime import datetime
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application, ApplicationStatus
from app.models.job import Job
from app.models.user import User
from app.models.notification import Notification, NotificationType
from app.services.cover_letter import generate_cover_letter
from app.services.form_filler import fill_and_submit_application

logger = logging.getLogger(__name__)


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run async code reliably inside Celery worker processes."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


@celery_app.task(bind=True, name="app.tasks.applications.generate_cover_letter_task", queue="applications")
def generate_cover_letter_task(self, application_id: int):
    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app:
            return {"error": "Application not found"}

        job = db.query(Job).filter(Job.id == app.job_id).first()
        user = db.query(User).filter(User.id == app.user_id).first()
        if not job or not user:
            return {"error": "Missing job or user"}

        job_dict = {
            "title": job.title,
            "company": job.company,
            "description": job.description,
            "requirements": job.requirements,
            "skills": job.skills,
        }
        user_dict = {
            **(user.profile_data or {}),
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "linkedin_url": user.linkedin_url,
        }

        letter = _run_async(generate_cover_letter(job_dict, user_dict))
        app.cover_letter = letter
        db.commit()
        return {"application_id": application_id, "generated": True}
    except Exception as e:
        logger.exception("generate_cover_letter_task failed")
        db.rollback()
        raise self.retry(exc=e, countdown=30, max_retries=2)
    finally:
        db.close()


@celery_app.task(bind=True, name="app.tasks.applications.submit_application_task", queue="applications")
def submit_application_task(self, application_id: int, dry_run: bool = False):
    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app:
            return {"error": "Application not found"}

        job = db.query(Job).filter(Job.id == app.job_id).first()
        user = db.query(User).filter(User.id == app.user_id).first()
        if not job or not user:
            return {"error": "Missing job or user"}

        if not job.url:
            app.status = ApplicationStatus.rejected
            app.automation_log = [{"error": "No application URL", "ts": datetime.utcnow().isoformat()}]
            db.commit()
            return {"error": "No URL for job"}

        app.status = ApplicationStatus.applying
        db.commit()

        profile = {
            **(user.profile_data or {}),
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "address": user.address,
            "linkedin_url": user.linkedin_url,
            "github_url": user.github_url,
            "portfolio_url": user.portfolio_url,
        }

        result = _run_async(
            fill_and_submit_application(
                job_url=job.url,
                user_profile=profile,
                cover_letter=app.cover_letter or "",
                resume_path=user.resume_path or "",
                dry_run=dry_run,
            )
        )

        app.automation_log = result.get("log", [])
        if result.get("success"):
            app.status = ApplicationStatus.pending if dry_run else ApplicationStatus.applied
            if not dry_run:
                app.applied_at = datetime.utcnow()
                db.add(Notification(
                    user_id=user.id,
                    type=NotificationType.application_submitted,
                    title=f"Applied to {job.title} at {job.company}",
                    message="Your application was submitted successfully.",
                    data={"job_id": job.id, "application_id": app.id},
                ))
        else:
            app.status = ApplicationStatus.pending
            logger.warning(f"Application {application_id} submission failed: {result.get('error')}")

        db.commit()
        return result
    except Exception as e:
        logger.exception("submit_application_task failed")
        db.rollback()
        raise self.retry(exc=e, countdown=60, max_retries=2)
    finally:
        db.close()
