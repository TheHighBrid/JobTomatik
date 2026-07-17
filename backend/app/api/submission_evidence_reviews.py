from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application, SubmissionEvidence
from app.models.job import Job
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.models.user import User
from app.schemas.submission_evidence_review import (
    SubmissionEvidenceReviewCreate,
    SubmissionEvidenceReviewOut,
    SubmissionEvidenceReviewPreflightOut,
)
from app.services.submission_evidence_review import (
    SubmissionEvidenceReviewError,
    build_evidence_review_preflight,
    build_evidence_snapshot,
    build_supervised_pilot_record,
    review_submission_evidence,
    serialize_evidence_review,
)


router = APIRouter(prefix="/applications", tags=["submission-evidence-review"])


def _owned_application(db: Session, application_id: int, user_id: int) -> Application:
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user_id)
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _application_job(db: Session, application: Application) -> Job:
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Application job not found")
    return job


def _application_evidence(
    db: Session,
    application_id: int,
    evidence_id: int,
) -> SubmissionEvidence:
    evidence = (
        db.query(SubmissionEvidence)
        .filter(
            SubmissionEvidence.id == evidence_id,
            SubmissionEvidence.application_id == application_id,
        )
        .first()
    )
    if not evidence:
        raise HTTPException(status_code=404, detail="Submission evidence not found")
    return evidence


@router.get(
    "/{application_id}/evidence/{evidence_id}/review-preflight",
    response_model=SubmissionEvidenceReviewPreflightOut,
)
def evidence_review_preflight(
    application_id: int,
    evidence_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _owned_application(db, application_id, current_user.id)
    job = _application_job(db, application)
    evidence = _application_evidence(db, application_id, evidence_id)
    return build_evidence_review_preflight(db, application, job, evidence)


@router.post(
    "/{application_id}/evidence/{evidence_id}/review",
    response_model=SubmissionEvidenceReviewOut,
    status_code=201,
)
def create_evidence_review(
    application_id: int,
    evidence_id: int,
    data: SubmissionEvidenceReviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _owned_application(db, application_id, current_user.id)
    job = _application_job(db, application)
    evidence = _application_evidence(db, application_id, evidence_id)
    try:
        review = review_submission_evidence(
            db,
            application,
            current_user,
            job,
            evidence,
            decision=data.decision,
            confirm_employer=data.confirm_employer,
            confirm_role=data.confirm_role,
            confirm_evidence_type=data.confirm_evidence_type,
            confirm_evidence_matches_application=data.confirm_evidence_matches_application,
            review_acknowledgement=data.review_acknowledgement,
            notes=data.notes,
        )
        db.commit()
        db.refresh(review)
    except SubmissionEvidenceReviewError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = build_evidence_snapshot(evidence)
    return serialize_evidence_review(review, current_snapshot=snapshot)


@router.get(
    "/{application_id}/evidence-reviews",
    response_model=List[SubmissionEvidenceReviewOut],
)
def list_evidence_reviews(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_application(db, application_id, current_user.id)
    reviews = (
        db.query(SubmissionEvidenceReview)
        .filter(SubmissionEvidenceReview.application_id == application_id)
        .order_by(
            SubmissionEvidenceReview.reviewed_at.desc(),
            SubmissionEvidenceReview.id.desc(),
        )
        .all()
    )
    values = []
    for review in reviews:
        evidence = db.query(SubmissionEvidence).filter(SubmissionEvidence.id == review.evidence_id).first()
        snapshot = build_evidence_snapshot(evidence) if evidence else None
        values.append(serialize_evidence_review(review, current_snapshot=snapshot))
    return values


@router.get("/{application_id}/supervised-pilot-record")
def export_supervised_pilot_record(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _owned_application(db, application_id, current_user.id)
    job = _application_job(db, application)
    try:
        return build_supervised_pilot_record(db, application, current_user, job)
    except SubmissionEvidenceReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
