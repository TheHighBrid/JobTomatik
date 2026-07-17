from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.supervised_pilot_roster import SupervisedPilotRosterOut
from app.services.greenhouse_pilot_ingestion import (
    GreenhousePilotIngestionError,
    read_greenhouse_pilot_readiness,
)
from app.services.supervised_pilot_roster import build_supervised_pilot_roster


router = APIRouter(prefix="/supervised-pilot", tags=["supervised-pilot"])


@router.get("/roster", response_model=SupervisedPilotRosterOut)
def supervised_pilot_roster(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        readiness = read_greenhouse_pilot_readiness()
    except GreenhousePilotIngestionError:
        readiness = None
    return build_supervised_pilot_roster(
        db,
        current_user,
        readiness=readiness,
    )
