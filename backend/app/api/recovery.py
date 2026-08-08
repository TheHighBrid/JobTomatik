from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.recovery import DeadLetterRequeueRequest, DeadLetterResolveRequest
from app.services.dead_letter import (
    DeadLetterError,
    list_dead_letters,
    reopen_dead_letter_after_dispatch_failure,
    requeue_dead_letter,
    resolve_dead_letter,
)
from app.tasks.agent_execution import dispatch_agent_run_task


router = APIRouter(prefix="/recovery", tags=["operations"])


@router.get("/dead-letters")
def get_dead_letters(
    status: str = Query(default="open", pattern="^(open|requeued|resolved|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "dead_letters": list_dead_letters(
            db,
            user_id=current_user.id,
            status=status,
            limit=limit,
        ),
        "submission_authorized": False,
        "outreach_authorized": False,
        "automatic_retry_enabled": False,
    }


@router.post("/dead-letters/{task_id}/requeue")
def requeue_dead_letter_task(
    task_id: int,
    payload: DeadLetterRequeueRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = requeue_dead_letter(
            db,
            user_id=current_user.id,
            task_id=task_id,
            acknowledgment=payload.acknowledgment,
        )
        # The state must exist before a worker can claim it.
        db.commit()
    except DeadLetterError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        dispatch = dispatch_agent_run_task.delay(result["run_id"])
    except Exception as exc:
        # A broker outage after the commit must not strand the task as requeued.
        # Reopen the retained envelope so the operator can retry the dispatch safely.
        try:
            reopen_dead_letter_after_dispatch_failure(
                db,
                user_id=current_user.id,
                task_id=task_id,
                error=str(exc),
            )
            db.commit()
        except DeadLetterError:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                "Dead-letter requeue was retained but dispatch failed; the dead letter "
                "was reopened for explicit retry"
            ),
        ) from exc

    return {
        **result,
        "dispatch_task_id": dispatch.id,
        "submission_authorized": False,
        "outreach_authorized": False,
    }


@router.post("/dead-letters/{task_id}/resolve")
def resolve_dead_letter_task(
    task_id: int,
    payload: DeadLetterResolveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = resolve_dead_letter(
            db,
            user_id=current_user.id,
            task_id=task_id,
            acknowledgment=payload.acknowledgment,
            note=payload.note,
        )
        db.commit()
        return result
    except DeadLetterError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
