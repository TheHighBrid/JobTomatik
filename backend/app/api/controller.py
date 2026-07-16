"""User-triggered automation controller endpoints.

These endpoints are intentionally preparation-only. They do not accept a live-submit
argument and always delegate application work with ``dry_run=True``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services.job_scraper import search_jobs
from app.tasks.applications import generate_cover_letter_task, submit_application_task
from app.api.jobs import _save_search_results


router = APIRouter(prefix="/controller", tags=["controller"])


def _approved_jobs(db: Session, limit: int) -> List[Job]:
    return (
        db.query(Job)
        .filter(Job.status == JobStatus.approved)
        .order_by(Job.relevance_score.desc(), Job.created_at.desc())
        .limit(limit)
        .all()
    )


def _prepare_approved_jobs(
    db: Session,
    user: User,
    jobs: Iterable[Job],
    *,
    source: str,
) -> Dict[str, Any]:
    prepared = 0
    skipped = 0
    results: List[Dict[str, Any]] = []
    countdown = 60

    for job in jobs:
        existing = (
            db.query(Application)
            .filter(Application.user_id == user.id, Application.job_id == job.id)
            .first()
        )
        if existing:
            skipped += 1
            results.append(
                {
                    "job_id": job.id,
                    "application_id": existing.id,
                    "skipped": True,
                    "reason": "application_already_exists",
                }
            )
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
        db.add(
            ApplicationEvent(
                application_id=app_obj.id,
                event_type="controller_dry_run_created",
                from_state=None,
                to_state=ApplicationAutomationState.preparing.value,
                payload={
                    "job_id": job.id,
                    "source": source,
                    "dry_run": True,
                    "live_submit_requested": False,
                },
            )
        )

        cover_letter_task = generate_cover_letter_task.delay(app_obj.id)
        submit_task = submit_application_task.apply_async(
            args=[app_obj.id],
            kwargs={"dry_run": True},
            countdown=countdown,
        )
        countdown += 30
        prepared += 1
        results.append(
            {
                "job_id": job.id,
                "application_id": app_obj.id,
                "cover_letter_task": cover_letter_task.id,
                "submit_task": submit_task.id,
                "dry_run": True,
                "skipped": False,
            }
        )

    db.commit()
    return {
        "prepared": prepared,
        # Compatibility alias used by the existing dashboard response handling.
        "applied": prepared,
        "skipped": skipped,
        "dry_run": True,
        "live_submission_enabled_by_controller": False,
        "results": results,
    }


@router.post("/bulk-prepare")
async def bulk_prepare(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Prepare approved jobs and run ATS flows only to their safe dry-run boundary."""

    result = _prepare_approved_jobs(
        db,
        current_user,
        _approved_jobs(db, limit),
        source="controller_bulk_prepare",
    )
    result["message"] = (
        f"Prepared {result['prepared']} approved application(s) in dry-run mode."
    )
    return result


@router.post("/safe-dry-run")
async def safe_dry_run(
    min_score: float = Query(0.55, ge=0.0, le=1.0),
    daily_limit: int = Query(15, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search, approve, and prepare applications without any live-submit option."""

    preferences = dict(current_user.job_preferences or {})
    keywords = ", ".join(
        preferences.get("preferred_titles", [])
        or preferences.get("skills", [])
        or ["AML analyst", "fraud analyst", "KYC analyst", "compliance analyst"]
    )
    locations = preferences.get("preferred_locations", [])
    location = locations[0] if locations else "Ottawa, Ontario"
    raw_jobs = await search_jobs(
        keywords=keywords,
        location=location,
        salary_min=preferences.get("min_salary"),
        sources=["jobbank", "indeed", "linkedin", "glassdoor"],
        limit=50,
    )
    saved_jobs = _save_search_results(db, current_user, raw_jobs, keywords)
    db.commit()

    queued_jobs = (
        db.query(Job)
        .filter(Job.status == JobStatus.queued, Job.relevance_score >= min_score)
        .order_by(Job.relevance_score.desc(), Job.created_at.desc())
        .limit(daily_limit)
        .all()
    )
    for job in queued_jobs:
        job.status = JobStatus.approved
    db.commit()

    result = _prepare_approved_jobs(
        db,
        current_user,
        _approved_jobs(db, daily_limit),
        source="controller_safe_dry_run",
    )
    result.update(
        {
            "jobs_found": len(raw_jobs),
            "jobs_saved": saved_jobs,
            "auto_approved": len(queued_jobs),
            "applications_queued": result["prepared"],
            "applications_skipped": result["skipped"],
            "message": (
                f"Safe dry run prepared {result['prepared']} application(s); "
                "no live submission was requested."
            ),
        }
    )
    return result
