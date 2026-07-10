from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.models.job import Job, JobStatus
from app.models.application import Application, ApplicationStatus, FollowUp
from app.models.notification import Notification, NotificationType
from app.schemas.application import (
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationOut,
    FollowUpCreate,
    FollowUpOut,
)
from app.tasks.applications import generate_cover_letter_task, submit_application_task

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationOut, status_code=201)
async def create_application(
    data: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == data.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = (
        db.query(Application)
        .filter(Application.user_id == current_user.id, Application.job_id == data.job_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Application already exists for this job")

    app = Application(
        user_id=current_user.id,
        job_id=data.job_id,
        cover_letter=data.cover_letter,
        notes=data.notes,
        status=ApplicationStatus.pending,
    )
    db.add(app)
    job.status = JobStatus.applied
    db.commit()
    db.refresh(app)

    if not data.cover_letter:
        generate_cover_letter_task.delay(app.id)

    return _load_application(db, app.id)


@router.post("/bulk-submit")
async def bulk_submit_applications(
    dry_run: bool = Query(False),
    limit: int = Query(10, ge=1, le=100),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    include_queued: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create and queue multiple applications for autonomous processing."""
    capped_limit = min(limit, 50)
    statuses = [JobStatus.approved]
    if include_queued:
        statuses.append(JobStatus.queued)

    existing_job_ids = [
        row[0]
        for row in db.query(Application.job_id)
        .filter(Application.user_id == current_user.id)
        .all()
    ]
    jobs = (
        db.query(Job)
        .filter(
            Job.status.in_(statuses),
            Job.relevance_score >= min_score,
            Job.url.isnot(None),
            ~Job.id.in_(existing_job_ids) if existing_job_ids else True,
        )
        .order_by(Job.relevance_score.desc(), Job.created_at.desc())
        .limit(capped_limit)
        .all()
    )

    queued = []
    for job in jobs:
        app = Application(user_id=current_user.id, job_id=job.id, status=ApplicationStatus.pending)
        db.add(app)
        job.status = JobStatus.applied
        db.flush()
        generate_cover_letter_task.delay(app.id)
        task = submit_application_task.apply_async(
            args=[app.id],
            kwargs={"dry_run": dry_run},
            countdown=60,
        )
        queued.append({"application_id": app.id, "job_id": job.id, "task_id": task.id, "dry_run": dry_run})

    db.commit()
    return {
        "queued": queued,
        "count": len(queued),
        "dry_run": dry_run,
    }


@router.get("", response_model=List[ApplicationOut])
async def list_applications(
    status: Optional[ApplicationStatus] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Application)
        .options(joinedload(Application.job), joinedload(Application.followups))
        .filter(Application.user_id == current_user.id)
    )
    if status:
        query = query.filter(Application.status == status)
    query = query.order_by(Application.created_at.desc())
    return query.offset((page - 1) * per_page).limit(per_page).all()


@router.get("/stats")
async def get_application_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    apps = db.query(Application).filter(Application.user_id == current_user.id).all()
    stats = {s.value: 0 for s in ApplicationStatus}
    for app in apps:
        stats[app.status.value] += 1
    stats["total"] = len(apps)
    return stats


@router.get("/{app_id}", response_model=ApplicationOut)
async def get_application(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = _load_application(db, app_id)
    if not app or app.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.patch("/{app_id}", response_model=ApplicationOut)
async def update_application(
    app_id: int,
    data: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    old_status = app.status
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(app, field, value)

    if data.status and data.status != old_status:
        db.add(Notification(
            user_id=current_user.id,
            type=NotificationType.status_change,
            title=f"Application status updated to {data.status.value}",
            message=f"Your application for {app.job.title if app.job else 'a job'} is now {data.status.value}.",
            data={"application_id": app_id, "old_status": old_status.value, "new_status": data.status.value},
        ))

    db.commit()
    return _load_application(db, app_id)


@router.post("/{app_id}/generate-cover-letter")
async def generate_cover_letter(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    task = generate_cover_letter_task.delay(app_id)
    return {"task_id": task.id, "status": "queued"}


@router.post("/{app_id}/submit")
async def submit_application(
    app_id: int,
    dry_run: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    task = submit_application_task.delay(app_id, dry_run=dry_run)
    return {"task_id": task.id, "status": "queued", "dry_run": dry_run}


@router.post("/{app_id}/followups", response_model=FollowUpOut, status_code=201)
async def create_followup(
    app_id: int,
    data: FollowUpCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    followup = FollowUp(
        application_id=app_id,
        scheduled_at=data.scheduled_at,
        subject=data.subject,
        message=data.message,
        recipient_email=data.recipient_email,
        status="pending",
    )
    db.add(followup)
    db.commit()
    db.refresh(followup)
    return followup


@router.get("/{app_id}/followups", response_model=List[FollowUpOut])
async def list_followups(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app.followups


def _load_application(db: Session, app_id: int) -> Optional[Application]:
    return (
        db.query(Application)
        .options(joinedload(Application.job), joinedload(Application.followups))
        .filter(Application.id == app_id)
        .first()
    )
