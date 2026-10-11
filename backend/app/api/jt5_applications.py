"""JT5 owner-authenticated application reservation endpoint.

Queue dispatch will be enabled only when the JT5 worker is installed and tested.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.application_execution_gate import ApplyDecision

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("/{application_id}/jt5/reserve")
def reserve_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        decision, attempt = reserve_jt5_attempt(
            db,
            application_id=application_id,
            authenticated_user_id=current_user.id,
        )
        db.commit()
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Application not found")
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Concurrent reservation; reload application status")
    if decision.decision is ApplyDecision.FORBIDDEN:
        raise HTTPException(status_code=404, detail="Application not found")
    if decision.decision is not ApplyDecision.EXECUTE:
        return {"status": decision.decision.value, "reason": decision.reason}
    return {
        "status": "reserved",
        "application_id": application_id,
        "attempt_reference": attempt.reference,
        "task_id": attempt.task_id,
        "dispatch_status": "not_dispatched",
    }
