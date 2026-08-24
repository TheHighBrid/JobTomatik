from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.adapter_health import build_adapter_health_report
from app.services.day32_observability import (
    build_day32_observability_report,
    sync_day32_operational_notifications,
)


router = APIRouter(prefix="/adapter-health", tags=["operations"])


@router.get("")
async def get_adapter_health(
    window_hours: int = Query(24, ge=1, le=720),
    failure_threshold: int | None = Query(None, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return user-scoped adapter health metrics and actionable alerts."""

    return build_adapter_health_report(
        db,
        current_user.id,
        window_hours=window_hours,
        failure_threshold=failure_threshold,
    )


@router.get("/observability")
async def get_operational_observability(
    window_hours: int = Query(24, ge=1, le=720),
    failure_threshold: int | None = Query(None, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return Day 32 source, adapter, policy, and material health for this account."""

    return build_day32_observability_report(
        db,
        current_user.id,
        window_hours=window_hours,
        failure_threshold=failure_threshold,
    )


@router.post("/observability/notifications/refresh")
async def refresh_operational_notifications(
    window_hours: int = Query(24, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist actionable incidents and at most one routine UTC-day digest."""

    result = sync_day32_operational_notifications(
        db,
        current_user.id,
        window_hours=window_hours,
    )
    db.commit()
    return result
