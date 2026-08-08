from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.operational_observability import (
    build_operational_observability_report,
    sync_operational_notifications,
)


router = APIRouter(prefix="/observability", tags=["operations"])


@router.get("")
def get_observability_report(
    window_hours: int = Query(default=24, ge=1, le=720),
    failure_threshold: int | None = Query(default=None, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return account-scoped source, adapter, policy, and material health."""
    return build_operational_observability_report(
        db,
        current_user.id,
        window_hours=window_hours,
        failure_threshold=failure_threshold,
    )


@router.post("/notifications/refresh")
def refresh_observability_notifications(
    window_hours: int = Query(default=24, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Materialize current incidents into deduplicated in-app notifications.

    This endpoint records alerts only. It does not retry work, change application
    state, change adapter maturity, or authorize any external action.
    """
    result = sync_operational_notifications(
        db,
        current_user.id,
        window_hours=window_hours,
    )
    db.commit()
    return result
