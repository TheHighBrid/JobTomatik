from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application, ManualReviewTask
from app.models.user import User
from app.services.manual_review_policy_revalidation import (
    ManualReviewPolicyRevalidationError,
    revalidate_answer_policy_manual_review,
    retire_stale_answer_policy_review_for_reprepare,
)

router = APIRouter(prefix="/applications", tags=["applications"])


def _owned_application_and_review(
    db: Session,
    *,
    user_id: int,
    app_id: int,
    review_id: int,
) -> tuple[Application, ManualReviewTask]:
    app = (
        db.query(Application)
        .filter(
            Application.id == app_id,
            Application.user_id == user_id,
        )
        .first()
    )
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    review = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.id == review_id,
            ManualReviewTask.application_id == app.id,
        )
        .first()
    )
    if not review:
        raise HTTPException(status_code=404, detail="Manual review task not found")
    return app, review


@router.post("/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies")
async def revalidate_answer_policy_review(
    app_id: int,
    review_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app, review = _owned_application_and_review(
        db,
        user_id=current_user.id,
        app_id=app_id,
        review_id=review_id,
    )
    try:
        result = revalidate_answer_policy_manual_review(
            db,
            app,
            review,
            user_id=current_user.id,
        )
    except ManualReviewPolicyRevalidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result


@router.post("/{app_id}/manual-reviews/{review_id}/retire-stale-for-reprepare")
async def retire_stale_answer_policy_review(
    app_id: int,
    review_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app, review = _owned_application_and_review(
        db,
        user_id=current_user.id,
        app_id=app_id,
        review_id=review_id,
    )
    try:
        result = retire_stale_answer_policy_review_for_reprepare(db, app, review)
    except ManualReviewPolicyRevalidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result
