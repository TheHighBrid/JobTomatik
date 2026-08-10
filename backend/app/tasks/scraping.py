import asyncio
import logging
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.intelligence import AgentRun
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.discovery_dedup import partition_new_discovery_jobs
from app.services.discovery_pipeline import persist_discovery_results
from app.services.discovery_search import search_jobs_with_diagnostics
from app.services.scheduler_policy import (
    build_search_plan,
    discovery_allowed_by_user_policy,
    rank_scheduler_candidates,
    scheduler_settings,
)
from app.services.operations_policy import evaluate_autopilot_policy
from app.services.operations_settings import get_operations_settings
from app.services.unattended_policy import shadow_dry_run_policy_context

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
    """Discover, score, evaluate, and store genuinely new results.

    Phase 9 records bounded per-source diagnostics on the durable discovery AgentRun.
    Scheduled searches suppress per-cycle success notifications; routine successes are
    summarized by the operations digest instead. Phase 11 optionally retains a shadow
    campaign identifier without forwarding it to external discovery providers.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"error": "User not found"}

        origin = str(search_params.get("_origin") or "interactive").strip().lower()
        raw_shadow_session_id = search_params.get("_shadow_session_id")
        try:
            shadow_session_id = (
                int(raw_shadow_session_id) if raw_shadow_session_id is not None else None
            )
        except (TypeError, ValueError):
            shadow_session_id = None
        provider_params = {
            key: value
            for key, value in dict(search_params or {}).items()
            if not str(key).startswith("_")
        }
        discovery = _run_async(search_jobs_with_diagnostics(**provider_params))
        raw_jobs = list(discovery.get("jobs") or [])
        source_diagnostics = list(discovery.get("source_diagnostics") or [])
        new_jobs, preexisting_duplicates = partition_new_discovery_jobs(db, raw_jobs)
        stats = persist_discovery_results(
            db,
            user,
            new_jobs,
            keywords=str(provider_params.get("keywords") or ""),
            search_params=provider_params,
        )
        stats["total_found"] = len(raw_jobs)
        stats["duplicates"] = int(stats.get("duplicates") or 0) + preexisting_duplicates
        stats["new_candidates"] = len(new_jobs)
        stats["source_diagnostics"] = source_diagnostics
        stats["origin"] = origin
        stats["shadow_session_id"] = shadow_session_id

        if stats.get("agent_run_id"):
            run = db.query(AgentRun).filter(AgentRun.id == stats["agent_run_id"]).first()
            if run is not None:
                run.result = {
                    **dict(run.result or {}),
                    "total_found": stats["total_found"],
                    "duplicates": stats["duplicates"],
                    "new_candidates": stats["new_candidates"],
                    "source_diagnostics": source_diagnostics,
                    "origin": origin,
                    "shadow_session_id": shadow_session_id,
                }

        if stats["saved"] > 0 and origin != "scheduler":
            db.add(
                Notification(
                    user_id=user_id,
                    type=NotificationType.new_match,
                    title=f"{stats['saved']} new job matches found",
                    message=(
                        f"We found {stats['saved']} new jobs matching your search for "
                        f"\"{provider_params.get('keywords', '')}\". Review them in your queue."
                    ),
                    data={
                        "count": stats["saved"],
                        "keywords": provider_params.get("keywords"),
                        "agent_run_id": stats["agent_run_id"],
                        "evaluations_created": stats["evaluations_created"],
                        "blocked": stats["blocked"],
                        "duplicates": stats["duplicates"],
                        "origin": origin,
                    },
                )
            )

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


def _run_scheduler_cycle_for_user(
    db,
    user: User,
    *,
    shadow_session_id: int | None = None,
) -> dict[str, Any]:
    """Run one policy-bounded scheduler cycle for exactly one account.

    Discovery may continue after an application cap is reached, but quiet hours,
    kill switches, and circuit breakers still pause the cycle. Application creation
    requires the complete user policy plus the live unattended job policy. The
    submission worker independently re-evaluates that job policy before browser work.

    ``shadow_session_id`` may activate only the narrow Phase 11 maturity exception.
    It never grants submission authority. A shadow cycle must independently prove the
    user's dry-run switch is on and global real submission is off before discovery,
    candidate ranking, application creation, or worker dispatch proceeds.
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
    user_dry_run_mode = bool(auto_settings.get("dry_run_mode", True))
    dry_run = user_dry_run_mode or not settings.allow_real_application_submit

    if shadow_session_id is not None and (
        not user_dry_run_mode or settings.allow_real_application_submit is not False
    ):
        return {
            "user_id": user.id,
            "skipped": True,
            "reason": "shadow_safety_invariant_blocked",
            "searched": False,
            "applications_queued": 0,
            "application_ids_queued": [],
            "blocked_job_reasons": {"shadow_safety_invariant_blocked": 1},
            "real_submission_enabled": bool(settings.allow_real_application_submit),
            # Report the explicit user switch rather than effective dry-run fallback so
            # the Phase 11 supervisor also detects a disabled dry-run policy.
            "dry_run": user_dry_run_mode,
            "user_dry_run_mode": user_dry_run_mode,
            "shadow_session_id": shadow_session_id,
        }

    if not search_enabled and not apply_enabled:
        return {
            "user_id": user.id,
            "skipped": True,
            "reason": "user_scheduler_disabled",
            "searched": False,
            "applications_queued": 0,
            "application_ids_queued": [],
            "blocked_job_reasons": {},
            "real_submission_enabled": settings.allow_real_application_submit,
            "dry_run": dry_run,
            "shadow_session_id": shadow_session_id,
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
            "application_ids_queued": [],
            "blocked_job_reasons": {},
            "real_submission_enabled": settings.allow_real_application_submit,
            "dry_run": dry_run,
            "shadow_session_id": shadow_session_id,
        }

    result: dict[str, Any] = {
        "user_id": user.id,
        "skipped": False,
        "reason": "scheduler_cycle_completed",
        "policy_decision": decision.to_dict(),
        "discovery_policy_allowed": discovery_allowed,
        "searched": False,
        "search_blocker": None,
        "search_task_id": None,
        "applications_queued": 0,
        "application_ids_queued": [],
        "blocked_job_reasons": {},
        "real_submission_enabled": settings.allow_real_application_submit,
        "user_dry_run_mode": user_dry_run_mode,
        "dry_run": dry_run,
        "shadow_session_id": shadow_session_id,
    }

    if search_enabled and discovery_allowed:
        search_plan = build_search_plan(user)
        if search_plan["ready"]:
            search_task = run_job_search.delay(
                user_id=user.id,
                search_params={
                    **search_plan["search_params"],
                    "_origin": "scheduler",
                    "_shadow_session_id": shadow_session_id,
                },
            )
            result["searched"] = True
            result["search_params"] = search_plan["search_params"]
            result["search_task_id"] = getattr(search_task, "id", None)
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

    if shadow_session_id is not None:
        with shadow_dry_run_policy_context(
            shadow_session_id=int(shadow_session_id),
            dry_run=True,
        ):
            ranked = rank_scheduler_candidates(
                db,
                user,
                limit=max(run_limit * 4, run_limit),
            )
    else:
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

    countdown = 120
    source = "full_stack_shadow_scheduler" if shadow_session_id is not None else "bounded_scheduler"
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
        db.add(
            ApplicationEvent(
                application_id=app_obj.id,
                event_type="application_created",
                from_state=None,
                to_state=ApplicationAutomationState.preparing.value,
                payload={
                    "job_id": job.id,
                    "source": source,
                    "dry_run": dry_run,
                    "shadow_session_id": shadow_session_id,
                },
            )
        )
        generate_cover_letter_task.delay(app_obj.id)
        worker_kwargs = {"dry_run": dry_run}
        if shadow_session_id is not None:
            worker_kwargs["shadow_session_id"] = int(shadow_session_id)
        submit_unattended_application_task.apply_async(
            args=[app_obj.id],
            kwargs=worker_kwargs,
            countdown=countdown,
        )
        result["applications_queued"] += 1
        result["application_ids_queued"].append(app_obj.id)
        countdown += 30
    db.commit()
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
            "applications_queued": sum(
                int(item.get("applications_queued") or 0) for item in cycles
            ),
            "cycles": cycles,
            "real_submission_enabled": settings.allow_real_application_submit,
        }
    except Exception as exc:
        logger.exception("daily_auto_search_all failed")
        db.rollback()
        return {"error": str(exc)}
    finally:
        db.close()
