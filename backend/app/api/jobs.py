from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.models.job import Job, JobStatus
from app.models.application import Application
from app.schemas.job import JobOut, JobSearch, JobListOut
from app.tasks.scraping import run_job_search

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/search", response_model=dict)
async def trigger_job_search(
    search: JobSearch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kick off a background job search and return immediately."""
    task = run_job_search.delay(
        user_id=current_user.id,
        search_params={
            "keywords": search.keywords,
            "location": search.location,
            "salary_min": search.salary_min,
            "salary_max": search.salary_max,
            "job_type": search.job_type.value if search.job_type else None,
            "sources": [s.value for s in search.sources] if search.sources else None,
            "limit": search.limit,
        },
    )
    return {"task_id": task.id, "status": "queued", "message": "Job search started in background"}


@router.get("/queue", response_model=JobListOut)
async def get_job_queue(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get jobs in the approval queue sorted by relevance score."""
    query = (
        db.query(Job)
        .filter(
            Job.status == JobStatus.queued,
            Job.relevance_score >= min_score,
        )
        .order_by(Job.relevance_score.desc(), Job.created_at.desc())
    )
    total = query.count()
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()
    return JobListOut(jobs=jobs, total=total, page=page, per_page=per_page)


@router.get("", response_model=JobListOut)
async def list_jobs(
    status: Optional[JobStatus] = None,
    source: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    if source:
        query = query.filter(Job.source == source)
    query = query.order_by(Job.created_at.desc())
    total = query.count()
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()
    return JobListOut(jobs=jobs, total=total, page=page, per_page=per_page)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/approve", response_model=JobOut)
async def approve_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """User approves this job — moves it to 'approved' status."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.approved
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/reject", response_model=JobOut)
async def reject_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """User rejects this job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.rejected
    db.commit()
    db.refresh(job)
    return job


@router.get("/task/{task_id}/status")
async def get_task_status(task_id: str, current_user: User = Depends(get_current_user)):
    from app.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }


@router.post("/bulk-apply")
async def bulk_apply(
    dry_run: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create applications and queue submission for all approved jobs."""
    from app.models.application import ApplicationStatus
    from app.tasks.applications import generate_cover_letter_task, submit_application_task

    approved_jobs = (
        db.query(Job)
        .filter(Job.status == JobStatus.approved)
        .limit(limit)
        .all()
    )

    results = []
    for job in approved_jobs:
        existing = (
            db.query(Application)
            .filter(Application.user_id == current_user.id, Application.job_id == job.id)
            .first()
        )
        if existing:
            results.append({"job_id": job.id, "application_id": existing.id, "skipped": True})
            continue

        app_obj = Application(
            user_id=current_user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
        )
        db.add(app_obj)
        job.status = JobStatus.applied
        db.flush()

        cl_task = generate_cover_letter_task.delay(app_obj.id)
        # Generate cover letter first (60s), then submit
        sub_task = submit_application_task.apply_async(
            args=[app_obj.id],
            kwargs={"dry_run": dry_run},
            countdown=60,
        )
        results.append({
            "job_id": job.id,
            "application_id": app_obj.id,
            "cover_letter_task": cl_task.id,
            "submit_task": sub_task.id,
            "dry_run": dry_run,
        })

    db.commit()
    return {
        "applied": len([r for r in results if not r.get("skipped")]),
        "skipped": len([r for r in results if r.get("skipped")]),
        "results": results,
    }


@router.post("/autopilot")
async def run_autopilot(
    dry_run: bool = Query(False),
    min_score: float = Query(0.55, ge=0.0, le=1.0),
    daily_limit: int = Query(15, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Full autonomous pipeline:
    1. Search jobs using user preferences
    2. Auto-approve all queued jobs above min_score
    3. Generate cover letters + submit applications
    """
    from app.models.application import ApplicationStatus
    from app.tasks.applications import generate_cover_letter_task, submit_application_task

    prefs = current_user.job_preferences or {}
    keywords = ", ".join(
        prefs.get("preferred_titles", []) or prefs.get("skills", [])
        or ["AML analyst", "fraud analyst", "KYC analyst", "compliance analyst"]
    )
    locations = prefs.get("preferred_locations", [])
    location = locations[0] if locations else "Ottawa, Ontario"

    # Step 1: kick off search
    search_task = run_job_search.delay(
        user_id=current_user.id,
        search_params={
            "keywords": keywords,
            "location": location,
            "salary_min": prefs.get("min_salary"),
            "sources": ["jobbank", "indeed", "linkedin", "glassdoor"],
            "limit": 50,
        },
    )

    # Step 2: auto-approve all queued jobs above threshold
    queued_jobs = (
        db.query(Job)
        .filter(Job.status == JobStatus.queued, Job.relevance_score >= min_score)
        .order_by(Job.relevance_score.desc())
        .limit(daily_limit)
        .all()
    )
    auto_approved = 0
    for job in queued_jobs:
        job.status = JobStatus.approved
        auto_approved += 1
    db.commit()

    # Step 3: create applications and queue submissions for all approved jobs
    approved_jobs = (
        db.query(Job)
        .filter(Job.status == JobStatus.approved)
        .limit(daily_limit)
        .all()
    )
    applied = 0
    skipped = 0
    for job in approved_jobs:
        existing = (
            db.query(Application)
            .filter(Application.user_id == current_user.id, Application.job_id == job.id)
            .first()
        )
        if existing:
            skipped += 1
            continue
        app_obj = Application(
            user_id=current_user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
        )
        db.add(app_obj)
        job.status = JobStatus.applied
        db.flush()
        generate_cover_letter_task.delay(app_obj.id)
        submit_application_task.apply_async(
            args=[app_obj.id],
            kwargs={"dry_run": dry_run},
            countdown=90,
        )
        applied += 1

    db.commit()

    return {
        "search_task_id": search_task.id,
        "auto_approved": auto_approved,
        "applications_queued": applied,
        "applications_skipped": skipped,
        "dry_run": dry_run,
        "message": (
            f"Autonomous pipeline running. "
            f"Search started, {auto_approved} jobs auto-approved, "
            f"{applied} applications queued for submission."
        ),
    }
