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
from app.models.intelligence import RecruiterContact
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationEventOut,
    ApplicationOut,
    ApplicationUpdate,
    FollowUpApprovalRequest,
    FollowUpCreate,
    FollowUpOut,
    FollowUpPreflightOut,
    FollowUpQueueOut,
    FollowUpRevokeRequest,
    FollowUpUpdate,
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
from app.services.submission_integrity import (
    DuplicateSubmissionIdentityError,
    build_application_idempotency_key,
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
    find_existing_application_for_aliases,
)
from app.services.supervised_followup import (
    APPROVAL_REVOKED,
    APPROVAL_UNAPPROVED,
    CLOSED_STATUSES,
    STATUS_DRAFT,
    STATUS_NEEDS_RECIPIENT,
    STATUS_SENDING,
    STATUS_SENT,
    SupervisedFollowUpError,
    approve_followup,
    build_followup_preflight,
    reset_followup_after_mutation,
    revoke_followup_approval,
)
from app.tasks.applications import generate_cover_letter_task, submit_application_task
from app.tasks.followup import send_followup

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


def _application_idempotency_key(user_id: int, job_id: int, aliases=None) -> str:
    return build_application_idempotency_key(
        user_id,
        aliases or [],
        fallback_job_id=job_id,
    )


def _exact_job_duplicate(data: ApplicationCreate, existing: Application) -> bool:
    return existing.job_id == data.job_id and not data.idempotency_key


def _owned_application(db: Session, user_id: int, app_id: int) -> Application:
    app = (
        db.query(Application)
        .filter(Application.id == app_id, Application.user_id == user_id)
        .first()
    )
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def _owned_followup(db: Session, user_id: int, app_id: int, followup_id: int) -> FollowUp:
    app = _owned_application(db, user_id, app_id)
    followup = (
        db.query(FollowUp)
        .filter(FollowUp.id == followup_id, FollowUp.application_id == app.id)
        .first()
    )
    if not followup:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    _ = followup.application
    return followup


def _owned_recruiter_contact(
    db: Session,
    user_id: int,
    contact_id: int | None,
) -> RecruiterContact | None:
    if contact_id is None:
        return None
    contact = (
        db.query(RecruiterContact)
        .filter(RecruiterContact.id == contact_id, RecruiterContact.user_id == user_id)
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="Recruiter contact not found")
    return contact


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def _normalize_company(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _validate_followup_contact(
    app: Application,
    current_user: User,
    contact: RecruiterContact | None,
    recipient_email: str | None,
) -> str | None:
    recipient = (recipient_email or "").strip() or None
    if contact:
        if app.job and _normalize_company(contact.company) != _normalize_company(app.job.company):
            raise HTTPException(
                status_code=409,
                detail="Recruiter contact company does not match this application.",
            )
        contact_email = (contact.email or "").strip()
        if not contact_email:
            raise HTTPException(
                status_code=409,
                detail="The selected recruiter contact does not have an email address.",
            )
        if recipient and _normalize_email(recipient) != _normalize_email(contact_email):
            raise HTTPException(
                status_code=409,
                detail="Recipient email must match the selected recruiter contact.",
            )
        recipient = contact_email
    if recipient and _normalize_email(recipient) == _normalize_email(current_user.email):
        raise HTTPException(
            status_code=409,
            detail="A recruiter follow-up cannot be addressed to the applicant's own email.",
        )
    return recipient


@router.post("", response_model=ApplicationOut, status_code=201)
async def create_application(
    data: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == data.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    aliases = build_submission_identity_aliases(job)
    existing_identity = find_existing_application_for_aliases(
        db,
        current_user.id,
        aliases,
    )
    if existing_identity:
        if _exact_job_duplicate(data, existing_identity):
            raise HTTPException(status_code=400, detail="Application already exists for this job")
        return _load_application(db, existing_identity.id)

    idempotency_key = data.idempotency_key or _application_idempotency_key(
        current_user.id,
        data.job_id,
        aliases,
    )
    existing_by_key = db.query(Application).filter(
        Application.submission_idempotency_key == idempotency_key
    ).first()
    if existing_by_key:
        if (
            data.idempotency_key
            and existing_by_key.user_id == current_user.id
            and existing_by_key.job_id == data.job_id
        ):
            return _load_application(db, existing_by_key.id)
        raise HTTPException(status_code=400, detail="Application already exists for this job")

    existing = db.query(Application).filter(
        Application.user_id == current_user.id,
        Application.job_id == data.job_id,
    ).first()
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
        source_listing_url=job.url,
        submission_idempotency_key=idempotency_key,
    )
    db.add(app)
    try:
        db.flush()
        claim_submission_identity_aliases(db, app, aliases)
    except (IntegrityError, DuplicateSubmissionIdentityError):
        db.rollback()
        existing = find_existing_application_for_aliases(
            db,
            current_user.id,
            aliases,
        )
        if not existing:
            existing = db.query(Application).filter(
                Application.submission_idempotency_key == idempotency_key
            ).first()
        if existing and existing.user_id == current_user.id:
            if _exact_job_duplicate(data, existing):
                raise HTTPException(status_code=400, detail="Application already exists for this job")
            return _load_application(db, existing.id)
        raise HTTPException(status_code=409, detail="Duplicate application request")

    db.add(ApplicationEvent(
        application_id=app.id,
        event_type="application_created",
        from_state=None,
        to_state=app.automation_state,
        payload={
            "job_id": job.id,
            "idempotency_key": idempotency_key,
            "identity_aliases": [item["alias_type"] for item in aliases],
        },
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
        aliases = build_submission_identity_aliases(job)
        if find_existing_application_for_aliases(db, current_user.id, aliases):
            continue
        idempotency_key = _application_idempotency_key(current_user.id, job.id, aliases)
        if db.query(Application.id).filter(
            Application.submission_idempotency_key == idempotency_key
        ).first():
            continue
        try:
            with db.begin_nested():
                app = Application(
                    user_id=current_user.id,
                    job_id=job.id,
                    status=ApplicationStatus.pending,
                    automation_state=ApplicationAutomationState.preparing.value,
                    source_listing_url=job.url,
                    submission_idempotency_key=idempotency_key,
                )
                db.add(app)
                db.flush()
                claim_submission_identity_aliases(db, app, aliases)
                job.status = JobStatus.applied
                db.add(ApplicationEvent(
                    application_id=app.id,
                    event_type="application_created",
                    from_state=None,
                    to_state=ApplicationAutomationState.preparing.value,
                    payload={
                        "job_id": job.id,
                        "source": "bulk_submit",
                        "identity_aliases": [item["alias_type"] for item in aliases],
                    },
                ))
                dispatch_plan.append({"application_id": app.id, "job_id": job.id})
        except (IntegrityError, DuplicateSubmissionIdentityError):
            continue

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

    return {"queued": queued, "count": len(queued), "dry_run": dry_run}


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
    return query.order_by(Application.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()


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
        Application.id == app_id,
        Application.user_id == current_user.id,
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    old_status = app.status
    updates = data.model_dump(exclude_none=True)
    requested_status = updates.pop("status", None)
    current_state = app.automation_state or ApplicationAutomationState.preparing.value

    if requested_status in {ApplicationStatus.pending, ApplicationStatus.applying} and submission_is_closed(app):
        raise HTTPException(
            status_code=409,
            detail="A closed application cannot be reopened through the generic status update endpoint.",
        )
    if (
        requested_status is not None
        and status_closes_submission(requested_status)
        and current_state == ApplicationAutomationState.applying.value
    ):
        raise HTTPException(
            status_code=409,
            detail="Wait for the active application attempt to finish before recording a terminal status.",
        )

    for field, value in updates.items():
        setattr(app, field, value)

    sessions_to_terminate = []
    if requested_status is not None:
        app.status = requested_status
        sessions_to_terminate = reconcile_user_reported_status(
            db,
            app,
            requested_status,
            user_id=current_user.id,
        )

    if requested_status and requested_status != old_status:
        db.add(Notification(
            user_id=current_user.id,
            type=NotificationType.status_change,
            title=f"Application status updated to {requested_status.value}",
            message=f"Your application for {app.job.title if app.job else 'a job'} is now {requested_status.value}.",
            data={
                "application_id": app_id,
                "old_status": old_status.value,
                "new_status": requested_status.value,
            },
        ))

    db.commit()
    for session in sessions_to_terminate:
        try:
            terminate_retained_browser(session)
        except BrowserHandoffUnavailable:
            pass
    return _load_application(db, app_id)


@router.post("/{app_id}/generate-cover-letter")
async def generate_cover_letter(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id,
        Application.user_id == current_user.id,
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
        Application.id == app_id,
        Application.user_id == current_user.id,
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    state = app.automation_state or ApplicationAutomationState.preparing.value
    if submission_is_closed(app):
        return {
            "status": "already_submitted",
            "dry_run": dry_run,
            "application_id": app.id,
            "application_status": app.status.value,
            "automation_state": state,
            "idempotency_key": app.submission_idempotency_key,
        }

    _require_live_submit_enabled(dry_run)
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
        Application.id == app_id,
        Application.user_id == current_user.id,
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
        Application.id == app_id,
        Application.user_id == current_user.id,
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
        Application.id == app_id,
        Application.user_id == current_user.id,
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
        Application.id == app_id,
        Application.user_id == current_user.id,
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
    app = _owned_application(db, current_user.id, app_id)
    contact = _owned_recruiter_contact(db, current_user.id, data.recruiter_contact_id)
    recipient = _validate_followup_contact(
        app,
        current_user,
        contact,
        data.recipient_email,
    )
    followup = FollowUp(
        application_id=app_id,
        recruiter_contact_id=contact.id if contact else None,
        scheduled_at=data.scheduled_at,
        subject=data.subject.strip(),
        message=data.message.strip(),
        recipient_email=recipient,
        status=STATUS_DRAFT if recipient and contact else STATUS_NEEDS_RECIPIENT,
        approval_status=APPROVAL_UNAPPROVED,
        delivery_metadata={
            "source": "authenticated_followup_api",
            "outreach_authorized": False,
        },
    )
    db.add(followup)
    db.flush()
    preflight = build_followup_preflight(db, followup, current_user)
    db.add(
        ApplicationEvent(
            application_id=app.id,
            event_type="followup_draft_created",
            from_state=app.automation_state,
            to_state=app.automation_state,
            payload={
                "followup_id": followup.id,
                "recruiter_contact_id": followup.recruiter_contact_id,
                "recipient_hash": preflight.get("recipient_hash"),
                "scheduled_at": followup.scheduled_at.isoformat(),
                "outreach_authorized": False,
            },
        )
    )
    db.commit()
    db.refresh(followup)
    return followup


@router.get("/{app_id}/followups", response_model=List[FollowUpOut])
async def list_followups(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_application(db, current_user.id, app_id)
    return (
        db.query(FollowUp)
        .filter(FollowUp.application_id == app_id)
        .order_by(FollowUp.created_at.desc(), FollowUp.id.desc())
        .all()
    )


@router.patch("/{app_id}/followups/{followup_id}", response_model=FollowUpOut)
async def update_followup(
    app_id: int,
    followup_id: int,
    data: FollowUpUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    followup = _owned_followup(db, current_user.id, app_id, followup_id)
    if followup.status in CLOSED_STATUSES or followup.status == STATUS_SENDING:
        raise HTTPException(status_code=409, detail="This follow-up can no longer be edited.")

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        return followup
    reset_followup_after_mutation(
        db,
        followup,
        reason="followup_payload_edited",
        user_id=current_user.id,
    )

    contact_id = updates.pop("recruiter_contact_id", followup.recruiter_contact_id)
    contact = _owned_recruiter_contact(db, current_user.id, contact_id)
    recipient_supplied = "recipient_email" in updates
    recipient = updates.pop("recipient_email", followup.recipient_email)
    if contact_id != followup.recruiter_contact_id and not recipient_supplied:
        recipient = contact.email if contact else None
    recipient = _validate_followup_contact(
        followup.application,
        current_user,
        contact,
        recipient,
    )

    followup.recruiter_contact_id = contact.id if contact else None
    followup.recipient_email = recipient
    if "scheduled_at" in updates:
        followup.scheduled_at = updates["scheduled_at"]
    if "subject" in updates:
        followup.subject = updates["subject"].strip()
    if "message" in updates:
        followup.message = updates["message"].strip()
    followup.status = STATUS_DRAFT if recipient and contact else STATUS_NEEDS_RECIPIENT

    db.add(
        ApplicationEvent(
            application_id=followup.application_id,
            event_type="followup_draft_updated",
            from_state=followup.application.automation_state,
            to_state=followup.application.automation_state,
            payload={
                "followup_id": followup.id,
                "approval_revoked": True,
                "outreach_authorized": False,
            },
        )
    )
    db.commit()
    db.refresh(followup)
    return followup


@router.get(
    "/{app_id}/followups/{followup_id}/preflight",
    response_model=FollowUpPreflightOut,
)
async def followup_preflight(
    app_id: int,
    followup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    followup = _owned_followup(db, current_user.id, app_id, followup_id)
    return build_followup_preflight(db, followup, current_user)


@router.post(
    "/{app_id}/followups/{followup_id}/approve",
    response_model=FollowUpPreflightOut,
)
async def approve_application_followup(
    app_id: int,
    followup_id: int,
    data: FollowUpApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    followup = _owned_followup(db, current_user.id, app_id, followup_id)
    try:
        result = approve_followup(
            db,
            followup,
            current_user,
            acknowledgment=data.acknowledgment,
        )
        db.commit()
        return result
    except SupervisedFollowUpError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{app_id}/followups/{followup_id}/revoke",
    response_model=FollowUpPreflightOut,
)
async def revoke_application_followup(
    app_id: int,
    followup_id: int,
    data: FollowUpRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    followup = _owned_followup(db, current_user.id, app_id, followup_id)
    if followup.status in CLOSED_STATUSES or followup.status == STATUS_SENDING:
        raise HTTPException(status_code=409, detail="This follow-up can no longer be revoked.")
    revoke_followup_approval(
        db,
        followup,
        reason=data.reason,
        user_id=current_user.id,
    )
    followup.approval_status = APPROVAL_REVOKED
    followup.status = STATUS_DRAFT if followup.recipient_email else STATUS_NEEDS_RECIPIENT
    db.commit()
    return build_followup_preflight(db, followup, current_user)


@router.post(
    "/{app_id}/followups/{followup_id}/send",
    response_model=FollowUpQueueOut,
)
async def queue_application_followup(
    app_id: int,
    followup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    followup = _owned_followup(db, current_user.id, app_id, followup_id)
    if followup.status == STATUS_SENT:
        return {
            "followup_id": followup.id,
            "status": STATUS_SENT,
            "task_id": None,
            "queued": False,
            "idempotent": True,
            "duplicate_delivery_prevented": True,
        }
    if followup.status == STATUS_SENDING:
        return {
            "followup_id": followup.id,
            "status": STATUS_SENDING,
            "task_id": None,
            "queued": False,
            "idempotent": True,
            "duplicate_delivery_prevented": True,
        }

    preflight = build_followup_preflight(db, followup, current_user)
    if not preflight["ready_for_delivery"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Follow-up is not ready for supervised delivery.",
                "blockers": preflight["blockers"],
                "approval_active": preflight["approval_active"],
                "due": preflight["due"],
                "provider_configured": preflight["provider_configured"],
                "global_send_enabled": preflight["global_send_enabled"],
            },
        )

    task = send_followup.delay(followup.id)
    return {
        "followup_id": followup.id,
        "status": followup.status,
        "task_id": str(task.id),
        "queued": True,
        "idempotent": False,
        "duplicate_delivery_prevented": False,
    }


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
