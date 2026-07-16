from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    FollowUp,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationEventOut,
    ApplicationOut,
    ApplicationUpdate,
    FollowUpCreate,
    FollowUpOut,
    ManualReviewResolve,
    ManualReviewTaskOut,
    SubmissionEvidenceOut,
)
from app.services.application_state import resolve_manual_review_task
from app.tasks.applications import generate_cover_letter_task, submit_application_task

router = APIRouter(prefix="/applications", tags=["applications"])
settings = get_settings()

LIVE_SUBMIT_BLOCKED_DETAIL = (
    "Real application submission is disabled. Set "
    "ALLOW_REAL_APPLICATION_SUBMIT=true only after supervised adapter certification."
)


def _require_live_submit_enabled(dry_run: bool) -> None:
    if not dry_run and not settings.allow_real_application_submit:
        raise HTTPException(status_code=409, detail=LIVE_SUBMIT_BLOCKED_DETAIL)


def _application_idempotency_key(user_id: int, job_id: int) -> str:
    return f"application:{user_id}:job:{job_id}"


@router.post("", response_model=ApplicationOut, status_code=201)
async def create_application(
    data: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == data.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    idempotency_key = data.idempotency_key or _application_idempotency_key(current_user.id, data.job_id)
    existing_by_key = (
        db.query(Application)
        .filter(Application.submission_idempotency_key == idempotency_key)
        .first()
    )
    if existing_by_key:
        if data.idempotency_key and existing_by_key.user_id == current_user.id and existing_by_key.job_id == data.job_id:
            return _load_application(db, existing_by_key.id)
        raise HTTPException(status_code=400, detail="Application already exists for this job")

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
        automation_state=(
            ApplicationAutomationState.ready_to_apply.value
            if data.cover_letter
            else ApplicationAutomationState.preparing.value
        ),
        submission_idempotency_key=idempotency_key,
    )
    db.add(app)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Application)
            .filter(Application.submission_idempotency_key == idempotency_key)
            .first()
        )
        if existing and existing.user_id == current_user.id and existing.job_id == data.job_id:
            return _load_application(db, existing.id)
        raise HTTPException(status_code=409, detail="Duplicate application request")

    db.add(ApplicationEvent(
        application_id=app.id,
        event_type="application_created",
        from_state=None,
        to_state=app.automation_state,
        payload={"job_id": job.id, "idempotency_key": idempotency_key},
    ))
    job.status = JobStatus.applied
    db.commit()
    db.refresh(app)

    if not data.cover_letter:
        generate_cover_letter_task.delay(app.id)

    return _load_application(db, app.id)


@router.post("/bulk-submit")
async def bulk_submit_applications(
    dry_run: bool = Query(True),
    limit: int = Query(10, ge=1, le=100),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    include_queued: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create and queue multiple applications for autonomous processing."""
    _require_live_submit_enabled(dry_run)

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
        idempotency_key = _application_idempotency_key(current_user.id, job.id)
        if db.query(Application.id).filter(Application.submission_idempotency_key == idempotency_key).first():
            continue
        app = Application(
            user_id=current_user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.preparing.value,
            submission_idempotency_key=idempotency_key,
        )
        db.add(app)
        job.status = JobStatus.applied
        db.flush()
        db.add(ApplicationEvent(
            application_id=app.id,
            event_type="application_created",
            from_state=None,
            to_state=ApplicationAutomationState.preparing.value,
            payload={"job_id": job.id, "source": "bulk_submit"},
        ))
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
        .options(
            joinedload(Application.job),
            joinedload(Application.followups),
            joinedload(Application.manual_reviews),
            joinedload(Application.submission_evidence),
            joinedload(Application.events),
        )
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
    automation = {s.value: 0 for s in ApplicationAutomationState}
    for app in apps:
        stats[app.status.value] += 1
        state = app.automation_state or ApplicationAutomationState.preparing.value
        automation[state] = automation.get(state, 0) + 1
    stats["total"] = len(apps)
    stats["automation_states"] = automation
    stats["open_manual_reviews"] = (
        db.query(ManualReviewTask.id)
        .join(Application, ManualReviewTask.application_id == Application.id)
        .filter(
            Application.user_id == current_user.id,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .count()
    )
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
    dry_run: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    _require_live_submit_enabled(dry_run)
    state = app.automation_state or ApplicationAutomationState.preparing.value
    if not dry_run and state in {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.confirmed.value,
    }:
        return {
            "status": "already_submitted",
            "dry_run": False,
            "application_id": app.id,
            "idempotency_key": app.submission_idempotency_key,
        }
    if state == ApplicationAutomationState.applying.value:
        raise HTTPException(status_code=409, detail="An application attempt is already in progress")

    task = submit_application_task.delay(app_id, dry_run=dry_run)
    return {
        "task_id": task.id,
        "status": "queued",
        "dry_run": dry_run,
        "idempotency_key": app.submission_idempotency_key,
    }


@router.get("/{app_id}/manual-reviews", response_model=List[ManualReviewTaskOut])
async def list_manual_reviews(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return (
        db.query(ManualReviewTask)
        .filter(ManualReviewTask.application_id == app_id)
        .order_by(ManualReviewTask.created_at.desc())
        .all()
    )


@router.post("/{app_id}/manual-reviews/{review_id}/resolve", response_model=ManualReviewTaskOut)
async def resolve_manual_review(
    app_id: int,
    review_id: int,
    data: ManualReviewResolve,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    review = db.query(ManualReviewTask).filter(
        ManualReviewTask.id == review_id,
        ManualReviewTask.application_id == app_id,
    ).first()
    if not review:
        raise HTTPException(status_code=404, detail="Manual review task not found")
    if review.status == ManualReviewStatus.resolved.value:
        return review

    resolve_manual_review_task(db, app, review, data.resolution_notes)
    db.commit()
    db.refresh(review)
    return review


@router.get("/{app_id}/evidence", response_model=List[SubmissionEvidenceOut])
async def list_submission_evidence(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return (
        db.query(SubmissionEvidence)
        .filter(SubmissionEvidence.application_id == app_id)
        .order_by(SubmissionEvidence.captured_at.desc())
        .all()
    )


@router.get("/{app_id}/events", response_model=List[ApplicationEventOut])
async def list_application_events(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id, Application.user_id == current_user.id
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return (
        db.query(ApplicationEvent)
        .filter(ApplicationEvent.application_id == app_id)
        .order_by(ApplicationEvent.created_at.desc())
        .all()
    )


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
        .options(
            joinedload(Application.job),
            joinedload(Application.followups),
            joinedload(Application.manual_reviews),
            joinedload(Application.submission_evidence),
            joinedload(Application.events),
        )
        .filter(Application.id == app_id)
        .first()
    )
