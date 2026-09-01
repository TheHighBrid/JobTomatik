from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.schemas.supervised_submission import (
    OperatorAssistedApprovalCreate,
    OperatorAssistedAuthorizationOut,
    OperatorAssistedConfirmationCreate,
    OperatorAssistedConfirmationOut,
    OperatorAssistedPreflightOut,
    SupervisedApprovalCreate,
    SupervisedApprovalOut,
    SupervisedApprovalRevoke,
    SupervisedPreflightOut,
    SupervisedSubmitQueued,
)
from app.services.application_integrity import submission_is_closed
from app.services.operator_assisted_submission import (
    OperatorAssistedSubmissionError,
    build_operator_assisted_preflight,
    issue_operator_assisted_approval,
    record_operator_confirmation,
    validate_operator_assisted_approval,
)
from app.services.submission_integrity import (
    SubmissionAttemptReservationError,
    reserve_submission_attempt,
)
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
    *,
    lock: bool = False,
) -> tuple[Application, User, Job]:
    query = db.query(Application).filter(
        Application.id == application_id,
        Application.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    application = query.first()
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
    db.commit()
    return HTTPException(status_code=409, detail=str(exc))


def _queued_attempt_payload(
    application: Application,
    approval: SubmissionApproval,
    attempt: SubmissionAttempt,
    *,
    created: bool,
) -> dict:
    return {
        "task_id": attempt.task_id,
        "status": "queued" if created else attempt.status,
        "application_id": application.id,
        "approval_reference": approval.reference,
        "attempt_reference": attempt.reference,
        "attempt_number": attempt.attempt_number,
        "idempotency_key": application.submission_idempotency_key,
        "idempotent": not created,
        "duplicate_final_action_prevented": not created,
        "dry_run": False,
    }


def _synchronize_submission_attempt_counter(
    db: Session,
    application: Application,
) -> None:
    """Keep the next reservation monotonic after a pre-worker publish failure.

    The application counter normally advances when the worker starts. A producer-side
    failure can leave an immutable blocked SubmissionAttempt behind before that worker
    transition happens. Reconcile the counter to the highest durable reservation so a
    newly approved retry receives the next unique attempt number instead of colliding
    with the blocked reservation.
    """

    latest = (
        db.query(SubmissionAttempt.attempt_number)
        .filter(SubmissionAttempt.application_id == application.id)
        .order_by(SubmissionAttempt.attempt_number.desc())
        .first()
    )
    latest_number = int(latest[0]) if latest else 0
    current_number = int(application.submission_attempt_count or 0)
    if latest_number > current_number:
        application.submission_attempt_count = latest_number
        db.flush()


def _publish_supervised_submission_task(
    application_id: int,
    approval_reference: str,
    attempt_reference: str,
):
    """Publish the exact supervised envelope without stale producer-side typing.

    The worker installs the authoritative supervised task gate and accepts the approval
    and durable attempt references. Celery's local Task.delay() argument checker is
    generated from the original task function before that worker-only wrapper exists,
    so it cannot represent the supervised envelope in an API producer process. Using
    send_task() publishes the named task exactly as the worker contract expects while
    retaining queue routing and all worker-side approval/attempt validation.
    """

    return submit_application_task.app.send_task(
        submit_application_task.name,
        args=[application_id],
        kwargs={
            "dry_run": False,
            "approval_reference": approval_reference,
            "attempt_reference": attempt_reference,
        },
        queue="applications",
    )


@router.get(
    "/applications/{application_id}/operator-assisted/preflight",
    response_model=OperatorAssistedPreflightOut,
)
async def operator_assisted_preflight(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, user, job = _owned_records(db, application_id, current_user.id)
    _require_open_submission(application)
    target_metadata = await resolve_supervised_target_metadata(job)
    return build_operator_assisted_preflight(
        db,
        application,
        user,
        job,
        target_metadata=target_metadata,
    )


@router.post(
    "/applications/{application_id}/operator-assisted/approvals",
    response_model=SupervisedApprovalOut,
    status_code=201,
)
async def create_operator_assisted_approval(
    application_id: int,
    data: OperatorAssistedApprovalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, user, job = _owned_records(
        db,
        application_id,
        current_user.id,
        lock=True,
    )
    _require_open_submission(application)
    target_metadata = await resolve_supervised_target_metadata(job)
    if target_metadata:
        persist_supervised_target_metadata(job, target_metadata)
    try:
        approval = issue_operator_assisted_approval(
            db,
            application,
            user,
            job,
            confirm_employer=data.confirm_employer,
            confirm_role=data.confirm_role,
            confirm_application_url=data.confirm_application_url,
            confirm_operator_final_click=data.confirm_operator_final_click,
            expires_in_minutes=data.expires_in_minutes,
            notes=data.notes,
            target_metadata=target_metadata,
        )
        db.commit()
        db.refresh(approval)
        return approval_safe_dict(approval)
    except OperatorAssistedSubmissionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/applications/{application_id}/operator-assisted/approvals/{reference}/authorize-final-click",
    response_model=OperatorAssistedAuthorizationOut,
)
async def authorize_operator_final_click(
    application_id: int,
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, user, job = _owned_records(
        db,
        application_id,
        current_user.id,
        lock=True,
    )
    _require_open_submission(application)
    target_metadata = await resolve_supervised_target_metadata(job)
    if target_metadata:
        persist_supervised_target_metadata(job, target_metadata)
    try:
        approval = validate_operator_assisted_approval(
            db,
            application,
            user,
            job,
            reference=reference,
            consume=True,
            target_metadata=target_metadata,
        )
        db.commit()
        db.refresh(approval)
        db.refresh(application)
    except OperatorAssistedSubmissionError as exc:
        raise _approval_error(db, exc) from exc

    return {
        "application_id": application.id,
        "approval_reference": approval.reference,
        "status": approval.status,
        "application_url": approval.application_url,
        "combined_payload_hash": approval.combined_payload_hash,
        "attempt_number": int(application.submission_attempt_count or 0),
        "operator_final_click_required": True,
        "automated_submission_authorized": False,
        "worker_task_created": False,
        "queue_created": False,
    }


@router.post(
    "/applications/{application_id}/operator-assisted/approvals/{reference}/confirmation",
    response_model=OperatorAssistedConfirmationOut,
)
async def record_operator_assisted_confirmation(
    application_id: int,
    reference: str,
    data: OperatorAssistedConfirmationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.confirm_submission_completed is not True:
        raise HTTPException(
            status_code=409,
            detail="confirm_submission_completed must be explicitly true",
        )
    application, user, job = _owned_records(
        db,
        application_id,
        current_user.id,
        lock=True,
    )
    try:
        evidence = record_operator_confirmation(
            db,
            application,
            user,
            job,
            reference=reference,
            evidence_type=data.evidence_type,
            final_url=data.final_url,
            confirmation_text=data.confirmation_text,
            external_application_id=data.external_application_id,
            notes=data.notes,
        )
        db.commit()
        db.refresh(evidence)
        db.refresh(application)
    except OperatorAssistedSubmissionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "application_id": application.id,
        "approval_reference": reference,
        "evidence_id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "final_url": evidence.final_url,
        "automation_state": application.automation_state,
        "independent_review_required": True,
        "phase_b_credit_granted": False,
    }


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
    # Hold the same application-row lock used by current Lever material mutation.
    # This keeps the final fresh approval validation and durable attempt reservation
    # atomic with respect to material regeneration/review, so a bundle cannot change
    # between preflight and reservation.
    application, user, job = _owned_records(
        db,
        application_id,
        current_user.id,
        lock=True,
    )
    _require_open_submission(application)

    existing_attempt = db.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application.id,
        SubmissionAttempt.approval_reference == reference,
    ).first()
    if existing_attempt:
        approval = db.query(SubmissionApproval).filter(
            SubmissionApproval.application_id == application.id,
            SubmissionApproval.reference == reference,
        ).first()
        if not approval:
            raise HTTPException(status_code=409, detail="Submission approval not found")
        return _queued_attempt_payload(application, approval, existing_attempt, created=False)

    target_metadata = await resolve_supervised_target_metadata(job)
    if target_metadata:
        persist_supervised_target_metadata(job, target_metadata)
    try:
        approval = validate_supervised_approval(
            db,
            application,
            user,
            job,
            reference=reference,
            consume=False,
            target_metadata=target_metadata,
        )
        _synchronize_submission_attempt_counter(db, application)
        attempt, created = reserve_submission_attempt(
            db,
            application,
            approval,
            task_id="reserved-" + str(uuid4()),
        )
        # The reservation is authoritative and visible before any queue message exists.
        db.commit()
    except IntegrityError:
        db.rollback()
        application, _, _ = _owned_records(db, application_id, current_user.id)
        approval = db.query(SubmissionApproval).filter(
            SubmissionApproval.application_id == application.id,
            SubmissionApproval.reference == reference,
        ).first()
        attempt = db.query(SubmissionAttempt).filter(
            SubmissionAttempt.application_id == application.id,
            SubmissionAttempt.approval_reference == reference,
        ).first()
        if approval and attempt:
            return _queued_attempt_payload(application, approval, attempt, created=False)
        raise HTTPException(status_code=409, detail="Duplicate submission queue request")
    except (SupervisedSubmissionApprovalError, SubmissionAttemptReservationError) as exc:
        raise _approval_error(db, exc)

    if created:
        try:
            # Publish the exact immutable approval + attempt envelope. The worker still
            # revalidates both records before consuming approval or touching a browser.
            task = _publish_supervised_submission_task(
                application_id,
                reference,
                attempt.reference,
            )
            attempt.task_id = str(task.id)
            db.commit()
        except Exception as exc:
            db.rollback()
            persisted = db.query(SubmissionAttempt).filter(
                SubmissionAttempt.id == attempt.id
            ).first()
            if persisted:
                persisted.status = "blocked"
                persisted.attempt_metadata = {
                    **dict(persisted.attempt_metadata or {}),
                    "block_reason": "queue_publish_uncertain",
                    "automatic_retry_allowed": False,
                    "publish_error": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
                db.commit()
            raise HTTPException(
                status_code=503,
                detail="Submission queue publication was uncertain; a new approval is required.",
            )

    return _queued_attempt_payload(application, approval, attempt, created=created)
