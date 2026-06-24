import asyncio
import logging
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.user import User
from app.models.notification import Notification, NotificationType
from app.services.job_scraper import search_jobs
from app.services.keyword_tagger import tag_job

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.scraping.run_job_search", queue="scraping")
def run_job_search(self, user_id: int, search_params: dict):
    """Scrape job boards and store new results, then notify the user."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"error": "User not found"}

        prefs = user.job_preferences or {}
        raw_jobs = asyncio.get_event_loop().run_until_complete(
            search_jobs(**search_params)
        )

        saved = 0
        for raw in raw_jobs:
            existing = (
                db.query(Job)
                .filter(Job.external_id == raw.get("external_id"))
                .first()
            )
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
                salary_currency=tagged.get("salary_currency", "USD"),
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
                raw_data=raw,
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
    """Recompute relevance scores for all queued jobs against each user's preferences."""
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
