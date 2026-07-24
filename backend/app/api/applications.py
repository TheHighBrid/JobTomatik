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
from app.services.application_integrity import (
    reconcile_user_reported_status,
    status_closes_submission,
    submission_is_closed,
)
from app.services.application_state import resolve_manual_review_task
from app.services.browser_handoff import (
    BrowserHandoffUnavailable,
    terminate_retained_browser,
)
from app.tasks.applications import generate_cover_letter_task, submit_application_task

router = APIRouter(prefix="/applications", tags=["applications"])
settings = get_settings()

LIVE_SUBMIT_BLOCKED_DETAIL = (
    "Real application submission is not enabled in the current release profile. "
    "Promote ALLOW_REAL_APPLICATION_SUBMIT=true after the selected adapter and "
    "operating profile meet the repository owner's release criteria."
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

    dispatch_plan = []
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
        dispatch_plan.append({"application_id": app.id, "job_id": job.id})

    # Workers use separate database connections. Commit every application before
    # publishing task messages so a fast worker cannot observe a missing row.
    db.commit()

    queued = []
    for item in dispatch_plan:
        generate_cover_letter_task.delay(item["application_id"])
        task = submit_application_task.apply_async(
            args=[item["application_id"]],
            kwargs={"dry_run": dry_run},
            countdown=60,
        )
        queued.append({
            **item,
            "task_id": task.id,
            "dry_run": dry_run,
        })

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
    return (
        query.order_by(Application.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
