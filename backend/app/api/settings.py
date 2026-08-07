from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.scheduler_policy import (
    SCHEDULER_DEFAULTS,
    SUPPORTED_AUTOPILOT_PLATFORMS,
    SUPPORTED_SEARCH_SOURCES,
)


router = APIRouter(prefix="/settings", tags=["settings"])

DEFAULT_SETTINGS = {
    **SCHEDULER_DEFAULTS,
    "auto_generate_cover_letters": True,
    "auto_followup": True,
    "auto_followup_days": 7,
    "email_on_status_change": True,
    "email_on_new_matches": False,
    "email_on_interview": True,
    "email_on_offer": True,
}

SCHEDULER_CONFLICT_FIELDS = {
    "auto_apply_daily_limit",
    "auto_apply_weekly_limit",
    "autopilot_employer_allow_list",
    "autopilot_employer_exclude_list",
}


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        normalized = str(item or "").strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


class SettingsUpdate(BaseModel):
    dry_run_mode: Optional[bool] = None
    auto_generate_cover_letters: Optional[bool] = None
    auto_followup: Optional[bool] = None
    auto_followup_days: Optional[int] = Field(default=None, ge=1, le=30)
    auto_search_enabled: Optional[bool] = None
    auto_apply_enabled: Optional[bool] = None
    auto_apply_min_score: Optional[float] = Field(default=None, ge=0.3, le=1.0)
    auto_apply_daily_limit: Optional[int] = Field(default=None, ge=1, le=50)
    auto_apply_weekly_limit: Optional[int] = Field(default=None, ge=1, le=200)
    auto_apply_daily_per_employer_limit: Optional[int] = Field(default=None, ge=1, le=10)
    quiet_hours_start_utc: Optional[int] = Field(default=None, ge=0, le=23)
    quiet_hours_end_utc: Optional[int] = Field(default=None, ge=0, le=23)
    autopilot_enabled_platforms: Optional[list[str]] = None
    autopilot_employer_allow_list: Optional[list[str]] = None
    autopilot_employer_exclude_list: Optional[list[str]] = None
    autopilot_allowed_locations: Optional[list[str]] = None
    autopilot_min_salary: Optional[int] = Field(default=None, ge=0, le=2_000_000)
    autopilot_allowed_seniority: Optional[list[str]] = None
    autopilot_allowed_languages: Optional[list[str]] = None
    scheduler_search_keywords: Optional[list[str]] = None
    scheduler_search_location: Optional[str] = Field(default=None, max_length=255)
    scheduler_search_sources: Optional[list[str]] = None
    scheduler_search_limit: Optional[int] = Field(default=None, ge=1, le=100)
    email_on_status_change: Optional[bool] = None
    email_on_new_matches: Optional[bool] = None
    email_on_interview: Optional[bool] = None
    email_on_offer: Optional[bool] = None

    @field_validator(
        "autopilot_enabled_platforms",
        "autopilot_employer_allow_list",
        "autopilot_employer_exclude_list",
        "autopilot_allowed_locations",
        "autopilot_allowed_seniority",
        "autopilot_allowed_languages",
        "scheduler_search_keywords",
        "scheduler_search_sources",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value):
        if value is None:
            return None
        return _normalize_list(value)

    @field_validator("autopilot_enabled_platforms")
    @classmethod
    def validate_platforms(cls, value: list[str] | None):
        if value is None:
            return value
        normalized = [item.lower() for item in value]
        unknown = sorted(set(normalized) - SUPPORTED_AUTOPILOT_PLATFORMS)
        if unknown:
            raise ValueError(f"Unsupported unattended platforms: {', '.join(unknown)}")
        return normalized

    @field_validator("scheduler_search_sources")
    @classmethod
    def validate_sources(cls, value: list[str] | None):
        if value is None:
            return value
        normalized = [item.lower() for item in value]
        unknown = sorted(set(normalized) - SUPPORTED_SEARCH_SOURCES)
        if unknown:
            raise ValueError(f"Unsupported scheduler search sources: {', '.join(unknown)}")
        if not normalized:
            raise ValueError("At least one scheduler search source is required")
        return normalized

    @field_validator("scheduler_search_location")
    @classmethod
    def normalize_location(cls, value: str | None):
        if value is None:
            return None
        return value.strip()

    @model_validator(mode="after")
    def validate_caps_and_lists(self):
        if (
            self.auto_apply_daily_limit is not None
            and self.auto_apply_weekly_limit is not None
            and self.auto_apply_weekly_limit < self.auto_apply_daily_limit
        ):
            raise ValueError("Weekly application limit cannot be lower than daily application limit")
        allow = {
            item.casefold() for item in (self.autopilot_employer_allow_list or [])
        }
        deny = {
            item.casefold() for item in (self.autopilot_employer_exclude_list or [])
        }
        overlap = sorted(allow & deny)
        if overlap:
            raise ValueError(
                "Employer allow and exclude lists cannot overlap: " + ", ".join(overlap)
            )
        return self


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
    updates = data.model_dump(exclude_none=True)

    # Validate cross-field scheduler invariants against the saved policy whenever
    # one side of that invariant is edited. Unrelated legacy settings remain
    # editable rather than being retroactively rejected by a new Phase 8 rule.
    if SCHEDULER_CONFLICT_FIELDS.intersection(updates):
        merged = {**DEFAULT_SETTINGS, **current, **updates}
        try:
            validated = SettingsUpdate(**merged).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        for key in updates:
            current[key] = validated[key]
    else:
        for key, value in updates.items():
            current[key] = value

    current_user.automation_settings = current
    db.commit()
    db.refresh(current_user)
    return {**DEFAULT_SETTINGS, **current}
