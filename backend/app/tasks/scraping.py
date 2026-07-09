import asyncio
import logging
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.user import User
from app.models.notification import Notification, NotificationType
from app.services.job_scraper import search_jobs
from app.services.keyword_tagger import tag_job

logger = logging.getLogger(__name__)
settings = get_settings()


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


@celery_app.task(bind=True, name="app.tasks.scraping.run_job_search", queue="scraping")
def run_job_search(self, user_id: int, search_params: dict):
    """Scrape job sources and store new results."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"error": "User not found"}

        prefs = user.job_preferences or {}
        raw_jobs = _run_async(search_jobs(**search_params))

        saved = 0
        for raw in raw_jobs:
            existing = db.query(Job).filter(Job.external_id == raw.get("external_id")).first()
            if existing:
                continue

            tagged = tag_job(raw, prefs)
            job = Job(
                external_id=tagged.get("external_id"),
                title=tagged["title"],
                company=tagged["company"],
                location=tagged.get("location"),
                salary_min=tagged.get("salary_min"),
                salary_max=tagged.get("salary_max"),
                salary_currency=tagged.get("salary_currency", "CAD"),
                job_type=tagged.get("job_type"),
                description=tagged.get("description"),
                requirements=tagged.get("requirements"),
                url=tagged.get("url"),
                source=tagged.get("source"),
                status=JobStatus.queued,
                tags=tagged.get("tags", []),
                skills=tagged.get("skills", []),
                seniority=tagged.get("seniority"),
                industry=tagged.get("industry"),
                relevance_score=tagged.get("relevance_score", 0.5),
                raw_data=raw.get("raw_data") or raw,
            )
            db.add(job)
            saved += 1

        if saved > 0:
            db.add(Notification(
                user_id=user_id,
                type=NotificationType.new_match,
                title=f"{saved} new job matches found",
                message=f"We found {saved} new jobs matching your search for \"{search_params.get('keywords', '')}\". Review them in your queue.",
                data={"count": saved, "keywords": search_params.get("keywords")},
            ))

        db.commit()
        return {"saved": saved, "total_found": len(raw_jobs)}

    except Exception as e:
        logger.exception("run_job_search failed")
        db.rollback()
        raise self.retry(exc=e, countdown=60, max_retries=3)
    finally:
        db.close()


@celery_app.task(name="app.tasks.scraping.refresh_all_scores", queue="scraping")
def refresh_all_scores():
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active == True).all()
        updated = 0
        for user in users:
            prefs = user.job_preferences or {}
            jobs = db.query(Job).filter(Job.status == JobStatus.queued).all()
            for job in jobs:
                job_dict = {
                    "title": job.title,
                    "skills": job.skills or [],
                    "location": job.location,
                    "salary_min": job.salary_min,
                }
                from app.services.keyword_tagger import compute_relevance
                job.relevance_score = compute_relevance(job_dict, prefs)
                updated += 1
        db.commit()
        return {"updated": updated}
    finally:
        db.close()


@celery_app.task(name="app.tasks.scraping.daily_auto_search_all", queue="scraping")
def daily_auto_search_all():
    """
    Safe autopilot:
    1. Search Job Bank only by default.
    2. Auto-approve high-score jobs.
    3. Queue dry runs unless ALLOW_REAL_APPLICATION_SUBMIT=true.
    """
    from app.models.application import Application, ApplicationStatus
    from app.tasks.applications import generate_cover_letter_task, submit_application_task

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active == True).all()
        kicked = 0
        for user in users:
            auto_settings = user.automation_settings or {}
            if not auto_settings.get("auto_search_enabled", True):
                continue

            prefs = user.job_preferences or {}
            keywords_list = prefs.get("preferred_titles") or prefs.get("skills") or []
            if not keywords_list:
                keywords_list = ["AML analyst", "fraud analyst", "KYC analyst"]
            keywords = ", ".join(keywords_list[:4])
            locations = prefs.get("preferred_locations", [])
            location = locations[0] if locations else "Ottawa, Ontario"

            run_job_search.delay(
                user_id=user.id,
                search_params={
                    "keywords": keywords,
                    "location": location,
                    "salary_min": prefs.get("min_salary"),
                    "sources": ["jobbank"],
                    "limit": 50,
                },
            )
            kicked += 1

            if auto_settings.get("auto_apply_enabled", True):
                min_score = float(auto_settings.get("auto_apply_min_score", 0.55))
                daily_limit = int(auto_settings.get("auto_apply_daily_limit", 15))

                queued = (
                    db.query(Job)
                    .filter(Job.status == JobStatus.queued, Job.relevance_score >= min_score)
                    .order_by(Job.relevance_score.desc())
                    .limit(daily_limit)
                    .all()
                )
                for job in queued:
                    job.status = JobStatus.approved
                db.commit()

                approved = db.query(Job).filter(Job.status == JobStatus.approved).limit(daily_limit).all()
                countdown = 120
                for job in approved:
                    existing = (
                        db.query(Application)
                        .filter(Application.user_id == user.id, Application.job_id == job.id)
                        .first()
                    )
                    if existing:
                        continue
                    app_obj = Application(user_id=user.id, job_id=job.id, status=ApplicationStatus.pending)
                    db.add(app_obj)
                    job.status = JobStatus.applied
                    db.flush()
                    generate_cover_letter_task.delay(app_obj.id)
                    submit_application_task.apply_async(
                        args=[app_obj.id],
                        kwargs={"dry_run": not settings.allow_real_application_submit},
                        countdown=countdown,
                    )
                    countdown += 30
                db.commit()

        return {"searched_for": kicked, "live_submit_enabled": settings.allow_real_application_submit}
    except Exception as e:
        logger.exception("daily_auto_search_all failed")
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
