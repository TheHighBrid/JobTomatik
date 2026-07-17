from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.adapter_health import build_adapter_health_report


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
