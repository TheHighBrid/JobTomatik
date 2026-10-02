from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.live_pilot import router as live_pilot_router
from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.autonomy_control_center import (
    AutonomyControlError,
    build_autonomy_control_snapshot,
    change_autonomy_mode,
    reject_application_from_autonomy_queue,
)
from app.services.operator_autonomy_control import MODE_DRAINING, MODE_PAUSED, MODE_RUNNING


router = APIRouter(prefix="/autonomy-control", tags=["autonomy-control"])
router.include_router(live_pilot_router)


class ControlActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class RejectApplicationRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.get("/snapshot")
def get_autonomy_control_snapshot(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_autonomy_control_snapshot(db, current_user)


def _change_mode(
    db: Session,
    current_user: User,
    *,
    mode: str,
    reason: str | None,
):
    change_autonomy_mode(db, current_user, mode=mode, reason=reason)
    return build_autonomy_control_snapshot(db, current_user)


@router.post("/pause")
def pause_autonomy(
    payload: ControlActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _change_mode(
        db,
        current_user,
        mode=MODE_PAUSED,
        reason=payload.reason or "Paused from Android autonomy control centre.",
    )


@router.post("/drain")
def drain_autonomy_queue(
    payload: ControlActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _change_mode(
        db,
        current_user,
        mode=MODE_DRAINING,
        reason=payload.reason or "Queue drain requested from Android autonomy control centre.",
    )


@router.post("/resume")
def resume_autonomy(
    payload: ControlActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _change_mode(
        db,
        current_user,
        mode=MODE_RUNNING,
        reason=payload.reason or "Resumed from Android autonomy control centre.",
    )


@router.post("/applications/{application_id}/reject")
def reject_autonomy_application(
    application_id: int,
    payload: RejectApplicationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return reject_application_from_autonomy_queue(
            db,
            current_user,
            application_id=application_id,
            reason=payload.reason,
        )
    except AutonomyControlError as exc:
        detail = str(exc)
        if detail == "Application not found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=409, detail=detail) from exc
