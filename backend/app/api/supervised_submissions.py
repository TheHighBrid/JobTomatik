from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.schemas.supervised_submission import (
    SupervisedApprovalCreate,
    SupervisedApprovalOut,
    SupervisedApprovalRevoke,
    SupervisedPreflightOut,
    SupervisedSubmitQueued,
)
from app.services.application_integrity import submission_is_closed
from app.services.supervised_submission import (
    SupervisedSubmissionApprovalError,
    approval_safe_dict,
    build_supervised_preflight,
    issue_supervised_approval,
    revoke_supervised_approval,
    validate_supervised_approval,
)
from app.services.supervised_target_identity import (
    persist_supervised_target_metadata,
    resolve_supervised_target_metadata,
)
from app.tasks.applications import submit_application_task


router = APIRouter(prefix="/supervised-submissions", tags=["supervised-submissions"])


def _owned_records(
    db: Session,
    application_id: int,
    user_id: int,
) -> tuple[Application, User, Job]:
    application = (
        db.query(Application)
        .filter(
            Application.id == application_id,
            Application.user_id == user_id,
        )
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    user = db.query(User).filter(User.id == user_id).first()
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not user or not job:
        raise HTTPException(status_code=409, detail="Application user or job is missing")
    return application, user, job


def _require_open_submission(application: Application) -> None:
    if submission_is_closed(application):
        raise HTTPException(
            status_code=409,
            detail="This application is already closed and cannot receive another supervised submission.",
        )


def _approval_error(db: Session, exc: Exception) -> HTTPException:
    # Expiry, metadata drift, and payload-change invalidations are deliberate state
    # changes and must remain auditable even though the request is rejected.
    db.commit()
    return HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/applications/{application_id}/preflight",
    response_model=SupervisedPreflightOut,
)
async def supervised_submission_preflight(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, user, job = _owned_records(db, application_id, current_user.id)
    _require_open_submission(application)
    target_metadata = await resolve_supervised_target_metadata(job)
    return build_supervised_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )


@router.post(
    "/applications/{application_id}/approvals",
    response_model=SupervisedApprovalOut,
    status_code=201,
)
async def create_supervised_submission_approval(
    application_id: int,
    data: SupervisedApprovalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, user, job = _owned_records(db, application_id, current_user.id)
    _require_open_submission(application)
    target_metadata = await resolve_supervised_target_metadata(job)
    if target_metadata:
        persist_supervised_target_metadata(job, target_metadata)
    try:
        approval = issue_supervised_approval(
            db,
            application,
            user,
            job,
            confirm_employer=data.confirm_employer,
            confirm_role=data.confirm_role,
            confirm_application_url=data.confirm_application_url,
            confirm_final_submit=data.confirm_final_submit,
            expires_in_minutes=data.expires_in_minutes,
            notes=data.notes,
            target_metadata=target_metadata,
        )
        db.commit()
        db.refresh(approval)
        return approval_safe_dict(approval)
    except SupervisedSubmissionApprovalError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/applications/{application_id}/approvals",
    response_model=List[SupervisedApprovalOut],
)
async def list_supervised_submission_approvals(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_records(db, application_id, current_user.id)
    approvals = (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.user_id == current_user.id,
        )
        .order_by(SubmissionApproval.created_at.desc(), SubmissionApproval.id.desc())
        .all()
    )
    return [approval_safe_dict(item) for item in approvals]


@router.post(
    "/applications/{application_id}/approvals/{reference}/revoke",
    response_model=SupervisedApprovalOut,
)
async def revoke_submission_approval(
    application_id: int,
    reference: str,
    data: SupervisedApprovalRevoke,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, user, _ = _owned_records(db, application_id, current_user.id)
    try:
        approval = revoke_supervised_approval(
            db,
            application,
            user,
            reference=reference,
            reason=data.reason,
        )
        db.commit()
        db.refresh(approval)
        return approval_safe_dict(approval)
    except SupervisedSubmissionApprovalError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/applications/{application_id}/approvals/{reference}/submit",
    response_model=SupervisedSubmitQueued,
)
async def queue_supervised_submission(
    application_id: int,
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, user, job = _owned_records(db, application_id, current_user.id)
    _require_open_submission(application)
    target_metadata = await resolve_supervised_target_metadata(job)
    if target_metadata:
        persist_supervised_target_metadata(job, target_metadata)
    try:
        validate_supervised_approval(
            db,
            application,
            user,
            job,
            reference=reference,
            consume=False,
            target_metadata=target_metadata,
        )
        # Persist the latest exact target metadata before the worker reads it.
        db.commit()
    except SupervisedSubmissionApprovalError as exc:
        raise _approval_error(db, exc)

    task = submit_application_task.delay(
        application_id,
        dry_run=False,
        approval_reference=reference,
    )
    return {
        "task_id": task.id,
        "status": "queued",
        "application_id": application.id,
        "approval_reference": reference,
        "idempotency_key": application.submission_idempotency_key,
        "dry_run": False,
    }
