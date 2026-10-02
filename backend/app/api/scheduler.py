from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.scheduler import SchedulerDispatchOut
from app.services.operator_autonomy_control import scheduler_control_decision
from app.services.scheduler_policy import build_scheduler_preview, scheduler_settings
from app.tasks.scraping import run_user_scheduler_cycle


router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/preview")
def get_scheduler_preview(
    candidate_limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    preview = build_scheduler_preview(db, current_user, candidate_limit=candidate_limit)
    preview["operator_control"] = scheduler_control_decision(current_user)
    return preview


@router.post("/run", response_model=SchedulerDispatchOut)
def dispatch_scheduler_cycle(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    control = scheduler_control_decision(current_user)
    if not control["allowed"]:
        raise HTTPException(status_code=409, detail=control)

    preview = build_scheduler_preview(db, current_user, candidate_limit=20)
    settings = scheduler_settings(current_user)
    search_enabled = bool(settings.get("auto_search_enabled"))
    apply_enabled = bool(settings.get("auto_apply_enabled"))

    if preview["global_kill_switch"]:
        raise HTTPException(status_code=409, detail="Global automation kill switch is active")
    if not preview["global_autopilot_enabled"]:
        raise HTTPException(status_code=409, detail="AUTOPILOT_ENABLED is false")
    if not search_enabled and not apply_enabled:
        raise HTTPException(status_code=409, detail="Scheduler is disabled for this account")

    discovery_ready = (
        search_enabled
        and bool(preview.get("discovery_policy_allowed"))
        and bool(preview["search_plan"].get("ready"))
    )
    autonomous_ready = (
        apply_enabled
        and bool(preview["user_policy"].get("allowed"))
        and int(preview["summary"]["allowed_candidate_count"]) > 0
    )
    if not discovery_ready and not autonomous_ready:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "No scheduler action is currently policy-ready",
                "user_policy": preview["user_policy"],
                "discovery_policy_allowed": preview.get("discovery_policy_allowed"),
                "search_plan": preview["search_plan"],
                "allowed_candidate_count": preview["summary"]["allowed_candidate_count"],
                "required_adapter_maturity": preview["required_adapter_maturity"],
            },
        )

    task = run_user_scheduler_cycle.delay(current_user.id)
    return {
        "queued": True,
        "user_id": current_user.id,
        "celery_task_id": task.id,
        "scheduler_state": preview["scheduler_state"],
        "preview": preview,
    }
