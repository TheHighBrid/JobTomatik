"""Pure target and confirmation helpers for ordinary Lever reliability."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.ats_lever import parse_lever_job_url


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
