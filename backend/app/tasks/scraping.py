import asyncio
import logging
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.discovery_dedup import partition_new_discovery_jobs
from app.services.discovery_pipeline import persist_discovery_results
from app.services.discovery_search import search_jobs
from app.services.scheduler_policy import (
    build_search_plan,
    discovery_allowed_by_user_policy,
    rank_scheduler_candidates,
    scheduler_settings,
)
from app.services.operations_policy import evaluate_autopilot_policy
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
    """Discover, score, evaluate, and store genuinely new results."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"error": "User not found"}

        raw_jobs = _run_async(search_jobs(**search_params))
        new_jobs, preexisting_duplicates = partition_new_discovery_jobs(db, raw_jobs)
        stats = persist_discovery_results(
            db,
            user,
            new_jobs,
            keywords=str(search_params.get("keywords") or ""),
            search_params=search_params,
        )
        stats["total_found"] = len(raw_jobs)
        stats["duplicates"] = int(stats.get("duplicates") or 0) + preexisting_duplicates
        stats["new_candidates"] = len(new_jobs)

        if stats["saved"] > 0:
            db.add(Notification(
                user_id=user_id,
                type=NotificationType.new_match,
                title=f"{stats['saved']} new job matches found",
                message=(
                    f"We found {stats['saved']} new jobs matching your search for "
                    f"\"{search_params.get('keywords', '')}\". Review them in your queue."
                ),
                data={
                    "count": stats["saved"],
                    "keywords": search_params.get("keywords"),
                    "agent_run_id": stats["agent_run_id"],
                    "evaluations_created": stats["evaluations_created"],
                    "blocked": stats["blocked"],
                    "duplicates": stats["duplicates"],
                },
            ))

        db.commit()
        return stats

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


def _run_scheduler_cycle_for_user(db, user: User) -> dict[str, Any]:
    """Run one policy-bounded scheduler cycle for exactly one account.

    Discovery may continue after an application cap is reached, but quiet hours,
    kill switches, and circuit breakers still pause the cycle. Application creation
    requires the complete user policy plus the live unattended job policy. The
    submission worker independently re-evaluates that job policy before browser work.
    """
    from app.models.application import (
        Application,
        ApplicationAutomationState,
        ApplicationEvent,
        ApplicationStatus,
    )
    from app.tasks.applications import generate_cover_letter_task
    from app.tasks.unattended import submit_unattended_application_task

    auto_settings = scheduler_settings(user)
    search_enabled = bool(auto_settings.get("auto_search_enabled", False))
    apply_enabled = bool(auto_settings.get("auto_apply_enabled", False))
    if not search_enabled and not apply_enabled:
        return {
            "user_id": user.id,
            "skipped": True,
            "reason": "user_scheduler_disabled",
            "searched": False,
            "applications_queued": 0,
            "blocked_job_reasons": {},
        }

    decision = evaluate_autopilot_policy(db, user)
    discovery_allowed = discovery_allowed_by_user_policy(decision)
    if not decision.allowed and not discovery_allowed:
        return {
            "user_id": user.id,
            "skipped": True,
            "reason": decision.code,
            "policy_decision": decision.to_dict(),
            "searched": False,
            "applications_queued": 0,
            "blocked_job_reasons": {},
        }

    result: dict[str, Any] = {
        "user_id": user.id,
        "skipped": False,
        "reason": "scheduler_cycle_completed",
        "policy_decision": decision.to_dict(),
        "discovery_policy_allowed": discovery_allowed,
        "searched": False,
        "search_blocker": None,
        "applications_queued": 0,
        "blocked_job_reasons": {},
        "real_submission_enabled": settings.allow_real_application_submit,
        "user_dry_run_mode": bool(auto_settings.get("dry_run_mode", True)),
    }

    if search_enabled and discovery_allowed:
        search_plan = build_search_plan(user)
        if search_plan["ready"]:
            run_job_search.delay(
                user_id=user.id,
                search_params=search_plan["search_params"],
            )
            result["searched"] = True
            result["search_params"] = search_plan["search_params"]
        else:
            result["search_blocker"] = {
                "code": search_plan["reason_code"],
                "reason": search_plan["reason"],
            }

    if not apply_enabled:
        return result
    if not decision.allowed:
        result["reason"] = decision.code
        return result

    remaining_daily = int(decision.metadata.get("remaining_daily", 0))
    remaining_weekly = int(decision.metadata.get("remaining_weekly", 0))
    requested_limit = int(auto_settings.get("auto_apply_daily_limit", remaining_daily or 1))
    run_limit = max(0, min(requested_limit, remaining_daily, remaining_weekly))
    if run_limit == 0:
        result["reason"] = "application_cap_reached"
        return result

    ranked = rank_scheduler_candidates(
        db,
        user,
        limit=max(run_limit * 4, run_limit),
    )
    approved_jobs: list[Job] = []
    approved_employers: set[str] = set()
    for item in ranked:
        job = item["job"]
        job_decision = item["decision"]
        if not job_decision.get("allowed"):
            code = str(job_decision.get("code") or "policy_blocked")
            result["blocked_job_reasons"][code] = (
                result["blocked_job_reasons"].get(code, 0) + 1
            )
            continue
        employer_key = str(job.company or "").strip().lower()
        if employer_key in approved_employers:
            result["blocked_job_reasons"]["same_run_employer_cap"] = (
                result["blocked_job_reasons"].get("same_run_employer_cap", 0) + 1
            )
            continue
        existing = (
            db.query(Application)
            .filter(Application.user_id == user.id, Application.job_id == job.id)
            .first()
        )
        if existing:
            result["blocked_job_reasons"]["existing_application"] = (
                result["blocked_job_reasons"].get("existing_application", 0) + 1
            )
            continue
        approved_jobs.append(job)
        approved_employers.add(employer_key)
        if len(approved_jobs) >= run_limit:
            break

    dry_run = bool(auto_settings.get("dry_run_mode", True)) or not settings.allow_real_application_submit
    countdown = 120
    for job in approved_jobs:
        job.status = JobStatus.approved
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
            payload={
                "job_id": job.id,
                "source": "bounded_scheduler",
                "dry_run": dry_run,
            },
        ))
        generate_cover_letter_task.delay(app_obj.id)
        submit_unattended_application_task.apply_async(
            args=[app_obj.id],
            kwargs={"dry_run": dry_run},
            countdown=countdown,
        )
        result["applications_queued"] += 1
        countdown += 30
    db.commit()
    result["dry_run"] = dry_run
    return result


@celery_app.task(name="app.tasks.scraping.run_user_scheduler_cycle", queue="scraping")
def run_user_scheduler_cycle(user_id: int):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            return {"error": "User not found"}
        return _run_scheduler_cycle_for_user(db, user)
    except Exception as exc:
        logger.exception("run_user_scheduler_cycle failed for user %s", user_id)
        db.rollback()
        return {"user_id": user_id, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.scraping.daily_auto_search_all", queue="scraping")
def daily_auto_search_all():
    """Run explicitly enabled, policy-bounded scheduled discovery and preparation."""
    operations = get_operations_settings()
    if not operations.autopilot_enabled:
        logger.info("Scheduled autopilot skipped because AUTOPILOT_ENABLED is false")
        return {
            "skipped": True,
            "reason": "global_autopilot_disabled",
            "users_considered": 0,
            "searched_for": 0,
            "applications_queued": 0,
        }

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active == True).all()
        cycles: list[dict[str, Any]] = []
        for user in users:
            cycle = _run_scheduler_cycle_for_user(db, user)
            cycles.append(cycle)
            if cycle.get("reason") not in {"user_scheduler_disabled", "scheduler_cycle_completed"}:
                logger.info(
                    "Scheduler cycle for user %s ended with %s",
                    user.id,
                    cycle.get("reason"),
                )
        return {
            "skipped": False,
            "users_considered": len(users),
            "searched_for": sum(1 for item in cycles if item.get("searched")),
            "applications_queued": sum(int(item.get("applications_queued") or 0) for item in cycles),
            "cycles": cycles,
            "real_submission_enabled": settings.allow_real_application_submit,
        }
    except Exception as exc:
        logger.exception("daily_auto_search_all failed")
        db.rollback()
        return {"error": str(exc)}
    finally:
        db.close()
