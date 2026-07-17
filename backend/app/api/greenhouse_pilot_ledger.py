from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.services.greenhouse_pilot_ingestion import (
    GreenhousePilotIngestionError,
    ingest_confirmed_supervised_application,
    read_greenhouse_pilot_readiness,
)


router = APIRouter(prefix="/greenhouse-pilot-ledger", tags=["greenhouse-pilot-ledger"])


def _owned_application(db: Session, application_id: int, user_id: int) -> Application:
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user_id)
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@router.post("/applications/{application_id}/ingest")
def ingest_application_pilot_record(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _owned_application(db, application_id, current_user.id)
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Application job not found")
    try:
        result = ingest_confirmed_supervised_application(
            db,
            application,
            current_user,
            job,
        )
        db.commit()
        return result
    except GreenhousePilotIngestionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/readiness")
def pilot_ledger_readiness(
    current_user: User = Depends(get_current_user),
):
    del current_user
    try:
        return read_greenhouse_pilot_readiness()
    except GreenhousePilotIngestionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
