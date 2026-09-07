from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application, ApplicationEvent, ManualReviewTask
from app.models.handoff import (
    ACTIVE_HANDOFF_STATUSES,
    HandoffChallengeType,
    ManualHandoffSession,
)
from app.models.user import User
from app.services.application_state import normalize_state
from app.services.manual_review_policy_revalidation import (
    ManualReviewPolicyRevalidationError,
    revalidate_answer_policy_manual_review,
    retire_stale_answer_policy_review_for_reprepare,
)
from app.services.manual_review_shape import effective_answer_policy_reason

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


def _repair_misclassified_answer_policy_review(
    db: Session,
    app: Application,
    review: ManualReviewTask,
) -> bool:
    effective_reason = effective_answer_policy_reason(
        reason_code=review.reason_code,
        summary=review.summary,
        details=review.details,
    )
    if effective_reason == str(review.reason_code or ""):
        return False

    active_final_handoff = (
        db.query(ManualHandoffSession.id)
        .filter(
            ManualHandoffSession.application_id == app.id,
            ManualHandoffSession.manual_review_id == review.id,
            ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
            ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
        )
        .first()
    )
    if active_final_handoff:
        raise ManualReviewPolicyRevalidationError(
            "This review still has an active final-submit handoff and cannot be reclassified."
        )

    previous_reason = str(review.reason_code or "")
    review.reason_code = effective_reason
    state = normalize_state(app.automation_state)
    db.add(ApplicationEvent(
        application_id=app.id,
        event_type="misclassified_answer_policy_review_repaired",
        from_state=state,
        to_state=state,
        payload={
            "review_id": review.id,
            "previous_reason_code": previous_reason,
            "effective_reason_code": effective_reason,
            "question_count": len((review.details or {}).get("questions") or []),
            "submission_authorized": False,
        },
    ))
    return True


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
        _repair_misclassified_answer_policy_review(db, app, review)
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
        _repair_misclassified_answer_policy_review(db, app, review)
        result = retire_stale_answer_policy_review_for_reprepare(db, app, review)
    except ManualReviewPolicyRevalidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result
