"""Permissive functional-test helpers for no-submit Phase 11 shadow execution.

Shadow testing must be able to exercise the real discovery, scheduler, queue, worker,
and browser/form paths without depending on production operating preferences. This
module never grants submission authority. It only supplies a search plan for an already
correlated no-submit shadow session.
"""

from __future__ import annotations

from typing import Any

from app.services.public_ats_discovery import PublicATSDiscoveryError, normalize_target
from app.services.scheduler_policy import build_search_plan


def build_shadow_search_plan(user) -> dict[str, Any]:
    """Return a usable test discovery plan without requiring production search prefs.

    Prefer the user's normal saved search plan when it is complete so shadow testing
    still exercises broad boards and intended criteria. If that production plan is
    incomplete, fall back to the explicit account-owned public ATS targets. Empty
    keywords/location are intentional in this fallback because the purpose is to test
    infrastructure and application mechanics, not job-interest filtering.
    """

    normal = build_search_plan(user)
    if normal.get("ready"):
        return {
            **normal,
            "policy_profile": "shadow_test",
            "source": "saved_search_plan",
            "production_search_preferences_required": False,
        }

    preferences = dict(getattr(user, "job_preferences", None) or {})
    targets: list[dict[str, str]] = []
    sources: list[str] = []
    seen: set[tuple[str, str]] = set()
    for raw in preferences.get("ats_targets") or []:
        if not isinstance(raw, dict):
            continue
        try:
            target = normalize_target(raw)
        except PublicATSDiscoveryError:
            continue
        key = (target["provider"], target["identifier"])
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
        if target["provider"] not in sources:
            sources.append(target["provider"])

    if not targets:
        return {
            "ready": False,
            "reason_code": "shadow_test_ats_target_missing",
            "reason": (
                "No-submit shadow testing requires at least one explicit account-owned "
                "public ATS target when the normal saved search plan is incomplete."
            ),
            "search_params": None,
            "policy_profile": "shadow_test",
            "source": "ats_fallback",
            "production_search_preferences_required": False,
        }

    return {
        "ready": True,
        "reason_code": "shadow_test_search_plan_ready",
        "reason": "No-submit shadow testing will use explicit public ATS targets.",
        "search_params": {
            "keywords": "",
            "location": "",
            "salary_min": None,
            "salary_max": None,
            "job_type": None,
            "sources": sources,
            "ats_targets": targets,
            "limit": 50,
        },
        "policy_profile": "shadow_test",
        "source": "ats_fallback",
        "production_search_preferences_required": False,
    }


__all__ = ["build_shadow_search_plan"]
