"""Authenticated read-only owner diagnostics API."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.operator_diagnostics import (
    build_operator_diagnostics,
    render_operator_status,
)


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/operator-diagnostics")
def operator_diagnostics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated owner's read-only OneHost status snapshot."""
    report = build_operator_diagnostics(db, current_user)
    report["text"] = render_operator_status(report)
    return report
