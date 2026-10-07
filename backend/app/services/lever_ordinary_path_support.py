"""Pure target and confirmation helpers for ordinary Lever reliability."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.services.ats_lever import parse_lever_job_url


CONTINUITY_KEY = "lever_ordinary_path"


EXPLICIT_CONFIRMATION_PHRASES = (
    "thank you for applying",
    "thank you for your application",
    "thanks for applying",
    "thanks for your application",
    "application submitted",
    "application received",
    "your application has been submitted",
    "your application was submitted",
    "application successfully submitted",
    "successfully submitted your application",
    "we have received your application",
    "we've received your application",
)


def normalize_text(value: Any) -> str:
    """Normalize employer confirmation text for phrase matching."""
    return " ".join(str(value or "").strip().lower().split())


def lever_target(url: str) -> Dict[str, Optional[str]]:
    """Return the canonical Lever site, posting id, and region tuple as a mapping."""
    site, posting_id, region = parse_lever_job_url(url)
    return {
        "site": site,
        "posting_id": posting_id,
        "region": region,
    }


def same_lever_target(left: str, right: str) -> bool:
    """Return whether both URLs identify the same concrete Lever posting."""
    left_target = lever_target(left)
    right_target = lever_target(right)
    return bool(
        left_target["site"]
        and left_target["posting_id"]
        and left_target == right_target
    )


def explicit_confirmation(final_url: str, confirmation_text: str) -> bool:
    """Require both a non-empty target and an explicit application-success phrase."""
    if not str(final_url or "").strip():
        return False
    text = normalize_text(confirmation_text)
    return any(phrase in text for phrase in EXPLICIT_CONFIRMATION_PHRASES)


def application_is_confirmed(application: Application) -> bool:
    """Return whether the application is already in a confirmed/submitted state."""
    return (
        application.status == ApplicationStatus.applied
        or application.automation_state
        in {
            ApplicationAutomationState.confirmed.value,
            ApplicationAutomationState.submitted.value,
        }
    )


def application_is_stale(
    application: Application,
    *,
    current: datetime,
    stale_after: timedelta,
) -> bool:
    """Return whether the application has exceeded the ordinary-path stale window."""
    updated = application.updated_at or application.created_at or current
    if getattr(updated, "tzinfo", None) is not None:
        updated = updated.replace(tzinfo=None)
    return current - updated >= stale_after


def recovery_target_state(application: Application) -> Optional[str]:
    """Choose the fail-closed state for a stale interrupted application."""
    if application.automation_state == ApplicationAutomationState.applying.value:
        return ApplicationAutomationState.submission_uncertain.value
    if application.automation_state in {
        ApplicationAutomationState.preparing.value,
        ApplicationAutomationState.ready_to_apply.value,
    }:
        return ApplicationAutomationState.needs_review.value
    return None


def unconfirmed_result(application: Application) -> Dict[str, Any]:
    """Return the canonical non-confirmed recovery result."""
    return {
        "application_id": application.id,
        "automation_state": application.automation_state,
        "confirmed": False,
    }


def continuity_ledger(application: Application) -> Dict[str, Any]:
    """Return and retain the ordinary-path continuity ledger mapping."""
    metadata = dict(application.application_target_metadata or {})
    ledger = dict(metadata.get(CONTINUITY_KEY) or {})
    metadata[CONTINUITY_KEY] = ledger
    application.application_target_metadata = metadata
    return ledger


def utc_now() -> datetime:
    """Return the naive UTC timestamp used by the existing persistence contract."""
    return datetime.utcnow()
