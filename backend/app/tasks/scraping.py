import asyncio
import logging
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.job_scraper import search_jobs
from app.services.keyword_tagger import tag_job
from app.services.operations_policy import evaluate_autopilot_policy
from app.services.unattended_policy import evaluate_unattended_job_policy
from app.services.operations_settings import get_operations_settings

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
    """Run explicitly enabled, policy-bounded scheduled discovery and preparation."""
    from app.models.application import (
        Application,
        ApplicationAutomationState,
        ApplicationEvent,
        ApplicationStatus,
    )
    from app.tasks.applications import generate_cover_letter_task
    from app.tasks.unattended import submit_unattended_application_task

    operations = get_operations_settings()
    if not operations.autopilot_enabled:
        logger.info("Scheduled autopilot skipped because AUTOPILOT_ENABLED is false")
        return {
            "skipped": True,
            "reason": "global_autopilot_disabled",
            "searched_for": 0,
            "applications_queued": 0,
        }

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active == True).all()
        searched_for = 0
        applications_queued = 0
        blocked_users = []
        disabled_platform_jobs = 0
        blocked_job_reasons: dict[str, int] = {}

        for user in users:
            auto_settings = dict(user.automation_settings or {})
            search_enabled = bool(auto_settings.get("auto_search_enabled", False))
            apply_enabled = bool(auto_settings.get("auto_apply_enabled", False))
            if not search_enabled and not apply_enabled:
                continue

            decision = evaluate_autopilot_policy(db, user)
            if not decision.allowed:
                blocked_users.append({"user_id": user.id, **decision.to_dict()})
                logger.info("Autopilot blocked for user %s: %s", user.id, decision.code)
                continue

            prefs = user.job_preferences or {}
            if search_enabled:
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
                        "sources": ["jobbank", "linkedin", "indeed"],
                        "limit": 50,
                    },
                )
                searched_for += 1

            if not apply_enabled:
                continue

            remaining_daily = int(decision.metadata.get("remaining_daily", 0))
            remaining_weekly = int(decision.metadata.get("remaining_weekly", 0))
            requested_limit = int(auto_settings.get("auto_apply_daily_limit", remaining_daily or 1))
            run_limit = max(0, min(requested_limit, remaining_daily, remaining_weekly))
            if run_limit == 0:
                continue

            min_score = float(auto_settings.get("auto_apply_min_score", 0.55))
            candidates = (
                db.query(Job)
                .filter(Job.status == JobStatus.queued, Job.relevance_score >= min_score)
                .order_by(Job.relevance_score.desc())
                .limit(max(run_limit * 4, run_limit))
                .all()
            )

            approved_jobs = []
            approved_employers: set[str] = set()
            for job in candidates:
                job_decision = evaluate_unattended_job_policy(db, user, job)
                if not job_decision.allowed:
                    disabled_platform_jobs += 1
                    blocked_job_reasons[job_decision.code] = (
                        blocked_job_reasons.get(job_decision.code, 0) + 1
                    )
                    logger.info(
                        "Autopilot job blocked for user %s, job %s: %s",
                        user.id,
                        job.id,
                        job_decision.code,
                    )
                    continue
                employer_key = str(job.company or "").strip().lower()
                if employer_key in approved_employers:
                    blocked_job_reasons["same_run_employer_cap"] = (
                        blocked_job_reasons.get("same_run_employer_cap", 0) + 1
                    )
                    continue
                job.status = JobStatus.approved
                approved_jobs.append(job)
                approved_employers.add(employer_key)
                if len(approved_jobs) >= run_limit:
                    break
            db.commit()

            countdown = 120
            for job in approved_jobs:
                existing = (
                    db.query(Application)
                    .filter(Application.user_id == user.id, Application.job_id == job.id)
                    .first()
                )
                if existing:
                    continue

                app_obj = Application(
                    user_id=user.id,
                    job_id=job.id,
                    status=ApplicationStatus.pending,
                    automation_state=ApplicationAutomationState.preparing.value,
                    submission_idempotency_key=f"application:{user.id}:job:{job.id}",
                )
                db.add(app_obj)
                db.flush()
                db.add(ApplicationEvent(
                    application_id=app_obj.id,
                    event_type="application_created",
                    from_state=None,
                    to_state=ApplicationAutomationState.preparing.value,
                    payload={"job_id": job.id, "source": "scheduled_autopilot"},
                ))
                generate_cover_letter_task.delay(app_obj.id)
                submit_unattended_application_task.apply_async(
                    args=[app_obj.id],
                    kwargs={"dry_run": not settings.allow_real_application_submit},
                    countdown=countdown,
                )
                applications_queued += 1
                countdown += 30
            db.commit()

        return {
            "skipped": False,
            "searched_for": searched_for,
            "applications_queued": applications_queued,
            "blocked_users": blocked_users,
            "disabled_platform_jobs": disabled_platform_jobs,
            "blocked_job_reasons": blocked_job_reasons,
            "real_submission_enabled": settings.allow_real_application_submit,
        }
    except Exception as e:
        logger.exception("daily_auto_search_all failed")
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
