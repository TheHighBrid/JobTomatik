from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/settings", tags=["settings"])

DEFAULT_SETTINGS = {
    "dry_run_mode": True,
    "auto_generate_cover_letters": True,
    "auto_followup": True,
    "auto_followup_days": 7,
    "auto_search_enabled": False,
    "auto_apply_enabled": False,
    "auto_apply_min_score": 0.6,
    "auto_apply_daily_limit": 10,
    "email_on_status_change": True,
    "email_on_new_matches": False,
    "email_on_interview": True,
    "email_on_offer": True,
}

class SettingsUpdate(BaseModel):
    dry_run_mode: Optional[bool] = None
    auto_generate_cover_letters: Optional[bool] = None
    auto_followup: Optional[bool] = None
    auto_followup_days: Optional[int] = None
    auto_search_enabled: Optional[bool] = None
    auto_apply_enabled: Optional[bool] = None
    auto_apply_min_score: Optional[float] = None
    auto_apply_daily_limit: Optional[int] = None
    email_on_status_change: Optional[bool] = None
    email_on_new_matches: Optional[bool] = None
    email_on_interview: Optional[bool] = None
    email_on_offer: Optional[bool] = None

@router.get("")
async def get_settings(current_user: User = Depends(get_current_user)):
    current = current_user.automation_settings or {}
    return {**DEFAULT_SETTINGS, **current}

@router.patch("")
async def update_settings(
    data: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current = dict(current_user.automation_settings or {})
    for k, v in data.model_dump(exclude_none=True).items():
        current[k] = v
    current_user.automation_settings = current
    db.commit()
    return {**DEFAULT_SETTINGS, **current}
