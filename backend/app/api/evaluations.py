from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.evaluation import OpportunityEvaluation
from app.models.job import Job
from app.models.user import User
from app.schemas.evaluation import (
    EvaluationFrameworkOut,
    OpportunityEvaluationCreate,
    OpportunityEvaluationOut,
)
from app.services.opportunity_evaluation import evaluate_opportunity, framework_manifest

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def _validate_owned_references(
    db: Session,
    user_id: int,
    *,
    job_id: int | None,
    application_id: int | None,
) -> None:
    if job_id is not None and db.query(Job.id).filter(Job.id == job_id).first() is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if application_id is not None:
        application = (
            db.query(Application)
            .filter(Application.id == application_id, Application.user_id == user_id)
            .first()
        )
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if job_id is not None and application.job_id != job_id:
            raise HTTPException(
                status_code=409,
                detail="Application and evaluation job do not match",
            )


@router.get("/framework", response_model=EvaluationFrameworkOut)
def get_evaluation_framework(
    current_user: User = Depends(get_current_user),
):
    del current_user
    return framework_manifest()


@router.get("", response_model=list[OpportunityEvaluationOut])
def list_evaluations(
    job_id: int | None = None,
    recommendation: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(OpportunityEvaluation).filter(
        OpportunityEvaluation.user_id == current_user.id
    )
    if job_id is not None:
        query = query.filter(OpportunityEvaluation.job_id == job_id)
    if recommendation:
        query = query.filter(OpportunityEvaluation.recommendation == recommendation)
    return query.order_by(OpportunityEvaluation.created_at.desc()).limit(limit).all()


@router.get("/{evaluation_id}", response_model=OpportunityEvaluationOut)
def get_evaluation(
    evaluation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(OpportunityEvaluation)
        .filter(
            OpportunityEvaluation.id == evaluation_id,
            OpportunityEvaluation.user_id == current_user.id,
        )
        .first()
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return evaluation


@router.post("", response_model=OpportunityEvaluationOut, status_code=status.HTTP_201_CREATED)
def create_evaluation(
    payload: OpportunityEvaluationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_owned_references(
        db,
        current_user.id,
        job_id=payload.job_id,
        application_id=payload.application_id,
    )
    result = evaluate_opportunity(
        payload.dimension_scores.model_dump(),
        hard_blockers=payload.hard_blockers,
        legitimacy_status=payload.legitimacy_status,
    )
    evaluation = OpportunityEvaluation(
        user_id=current_user.id,
        job_id=payload.job_id,
        application_id=payload.application_id,
        framework_version=result["framework_version"],
        recommendation=result["recommendation"],
        weighted_score=result["weighted_score"],
        dimension_scores=result["dimension_scores"],
        analysis_blocks=payload.analysis_blocks,
        legitimacy_status=result["legitimacy_status"],
        hard_blockers=result["hard_blockers"],
        source_snapshot=payload.source_snapshot,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation
