from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.schemas.supervised_pilot_dossier import SupervisedPilotDossierOut
from app.schemas.supervised_pilot_roster import (
    SupervisedPilotCandidateImportIn,
    SupervisedPilotCandidateImportOut,
    SupervisedPilotRosterOut,
)
from app.services.greenhouse_pilot_ingestion import (
    GreenhousePilotIngestionError,
    read_greenhouse_pilot_readiness,
)
from app.services.supervised_pilot_dossier import (
    SupervisedPilotDossierError,
    build_supervised_pilot_dossier,
)
from app.services.supervised_pilot_intake import (
    SupervisedPilotIntakeError,
    import_supervised_pilot_candidate,
)
from app.services.supervised_pilot_roster import build_supervised_pilot_roster


router = APIRouter(prefix="/supervised-pilot", tags=["supervised-pilot"])


def _readiness_or_none():
    try:
        return read_greenhouse_pilot_readiness()
    except GreenhousePilotIngestionError:
        return None


def _owned_application_records(
    db: Session,
    application_id: int,
    user_id: int,
) -> tuple[Application, Job]:
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
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        raise HTTPException(status_code=409, detail="Application job is missing")
    return application, job


@router.post(
    "/candidates",
    response_model=SupervisedPilotCandidateImportOut,
)
def import_supervised_pilot_application_candidate(
    data: SupervisedPilotCandidateImportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = import_supervised_pilot_candidate(
            db,
            current_user,
            employer=data.employer,
            role=data.role,
            application_url=data.application_url,
            location=data.location,
            notes=data.notes,
            source_reference=data.source_reference,
        )
    except SupervisedPilotIntakeError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    return result


@router.get("/roster", response_model=SupervisedPilotRosterOut)
def supervised_pilot_roster(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_supervised_pilot_roster(
        db,
        current_user,
        readiness=_readiness_or_none(),
    )


@router.get(
    "/applications/{application_id}/dossier",
    response_model=SupervisedPilotDossierOut,
)
def supervised_pilot_application_dossier(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, job = _owned_application_records(
        db,
        application_id,
        current_user.id,
    )
    try:
        return build_supervised_pilot_dossier(
            db,
            application,
            current_user,
            job,
            readiness=_readiness_or_none(),
        )
    except SupervisedPilotDossierError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
