from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.models.job import Job, JobStatus
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
