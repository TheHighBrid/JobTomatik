from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.config import get_settings
from app.models.job import Job, JobStatus
from app.services.operations_policy import AutomationDecision, evaluate_autopilot_policy
from app.services.operations_settings import get_operations_settings
from app.services.unattended_policy import (
    REQUIRED_AUTONOMOUS_MATURITY,
    evaluate_unattended_job_policy,
    live_platform_maturities,
)


SCHEDULER_POLICY_VERSION = "bounded-autonomy-v1"

SUPPORTED_SEARCH_SOURCES = {
    "jobbank",
    "linkedin",
    "indeed",
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
}
SUPPORTED_AUTOPILOT_PLATFORMS = {
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
}

SCHEDULER_DEFAULTS: dict[str, Any] = {
    "dry_run_mode": True,
    "auto_search_enabled": False,
    "auto_apply_enabled": False,
    "auto_apply_min_score": 0.65,
    "auto_apply_daily_limit": 5,
    "auto_apply_weekly_limit": 20,
    "auto_apply_daily_per_employer_limit": 1,
    "quiet_hours_start_utc": 0,
    "quiet_hours_end_utc": 6,
    "autopilot_enabled_platforms": [],
    "autopilot_employer_allow_list": [],
    "autopilot_employer_exclude_list": [],
    "autopilot_allowed_locations": [],
    "autopilot_min_salary": 0,
    "autopilot_allowed_seniority": [],
    "autopilot_allowed_languages": [],
    "scheduler_search_keywords": [],
    "scheduler_search_location": "",
    "scheduler_search_sources": ["jobbank", "linkedin", "indeed"],
    "scheduler_search_limit": 50,
}
SCHEDULER_SETTING_FIELDS = frozenset(SCHEDULER_DEFAULTS)


def _list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw: Iterable[Any] = value.split(",")
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


def scheduler_policy_is_current(user) -> bool:
    raw = dict(user.automation_settings or {})
    return str(raw.get("scheduler_policy_version") or "") == SCHEDULER_POLICY_VERSION


def scheduler_settings(user) -> dict[str, Any]:
    operations = get_operations_settings()
    raw = dict(user.automation_settings or {})
    policy_current = scheduler_policy_is_current(user)
    merged = {
        **SCHEDULER_DEFAULTS,
        "auto_apply_daily_limit": operations.default_daily_cap,
        "auto_apply_weekly_limit": operations.default_weekly_cap,
        "quiet_hours_start_utc": operations.quiet_hours_start_utc,
        "quiet_hours_end_utc": operations.quiet_hours_end_utc,
        **raw,
    }
    for key in (
        "autopilot_enabled_platforms",
        "autopilot_employer_allow_list",
        "autopilot_employer_exclude_list",
        "autopilot_allowed_locations",
        "autopilot_allowed_seniority",
        "autopilot_allowed_languages",
        "scheduler_search_keywords",
        "scheduler_search_sources",
    ):
        merged[key] = _list_values(merged.get(key))

    # Historical builds exposed auto-search/auto-apply as true defaults. Values
    # persisted by those builds are not evidence of explicit Phase 8 consent.
    if not policy_current:
        merged["auto_search_enabled"] = False
        merged["auto_apply_enabled"] = False
        merged["dry_run_mode"] = True
    merged["scheduler_policy_version"] = raw.get("scheduler_policy_version")
    merged["scheduler_policy_current"] = policy_current
    return merged


def discovery_allowed_by_user_policy(decision: AutomationDecision) -> bool:
    """Application caps stop application creation, not safe scheduled discovery."""
    return decision.allowed or decision.code == "application_cap_reached"


def build_search_plan(user) -> dict[str, Any]:
    settings = scheduler_settings(user)
    preferences = dict(user.job_preferences or {})

    keywords = settings["scheduler_search_keywords"]
    if not keywords:
        keywords = _list_values(
            preferences.get("preferred_titles") or preferences.get("skills")
        )
    if not keywords:
        return {
            "ready": False,
            "reason_code": "search_keywords_missing",
            "reason": "Scheduled discovery requires explicit search keywords or profile titles/skills.",
            "search_params": None,
        }

    location = str(settings.get("scheduler_search_location") or "").strip()
    if not location:
        preferred_locations = _list_values(preferences.get("preferred_locations"))
        location = preferred_locations[0] if preferred_locations else ""
    if not location:
        return {
            "ready": False,
            "reason_code": "search_location_missing",
            "reason": "Scheduled discovery requires an explicit search location or preferred location.",
            "search_params": None,
        }

    sources = [
        item.lower()
        for item in settings["scheduler_search_sources"]
        if item.lower() in SUPPORTED_SEARCH_SOURCES
    ]
    ats_targets = [
        target
        for target in (preferences.get("ats_targets") or [])
        if isinstance(target, dict)
    ]
    for target in ats_targets:
        provider = str(target.get("provider") or "").strip().lower()
        if provider in SUPPORTED_SEARCH_SOURCES and provider not in sources:
            sources.append(provider)
    if not sources:
        return {
            "ready": False,
            "reason_code": "search_sources_missing",
            "reason": "Scheduled discovery requires at least one supported job source.",
            "search_params": None,
        }

    try:
        limit = max(1, min(100, int(settings.get("scheduler_search_limit", 50))))
    except (TypeError, ValueError):
        limit = 50

    return {
        "ready": True,
        "reason_code": "search_plan_ready",
        "reason": "Scheduled discovery has explicit keywords, location, and sources.",
        "search_params": {
            "keywords": ", ".join(keywords[:8]),
            "location": location,
            "salary_min": preferences.get("min_salary"),
            "sources": sources,
            "ats_targets": ats_targets,
            "limit": limit,
        },
    }


def _parse_deadline(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def job_deadline(job: Job) -> datetime | None:
    raw = dict(job.raw_data or {})
    for key in (
        "closing_date",
        "application_deadline",
        "deadline",
        "expires_at",
    ):
        parsed = _parse_deadline(raw.get(key))
        if parsed:
            return parsed
    return None


def candidate_priority(job: Job, now: datetime | None = None) -> tuple[float, dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    base = max(0.0, min(1.0, float(job.relevance_score or 0.0))) * 100.0
    deadline = job_deadline(job)
    urgency = 0.0
    days_remaining: float | None = None
    if deadline:
        days_remaining = (deadline - current).total_seconds() / 86400.0
        if days_remaining < 0:
            urgency = -100.0
        elif days_remaining <= 1:
            urgency = 18.0
        elif days_remaining <= 3:
            urgency = 12.0
        elif days_remaining <= 7:
            urgency = 7.0
        elif days_remaining <= 14:
            urgency = 3.0
    score = round(base + urgency, 3)
    return score, {
        "match_score": round(float(job.relevance_score or 0.0), 4),
        "deadline": deadline.isoformat() if deadline else None,
        "days_remaining": round(days_remaining, 2) if days_remaining is not None else None,
        "urgency_boost": urgency,
    }


def rank_scheduler_candidates(
    db,
    user,
    *,
    limit: int = 20,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    settings = scheduler_settings(user)
    try:
        min_score = max(0.0, min(1.0, float(settings.get("auto_apply_min_score", 0.65))))
    except (TypeError, ValueError):
        min_score = 0.65

    rows = (
        db.query(Job)
        .filter(Job.status == JobStatus.queued, Job.relevance_score >= min_score)
        .limit(max(limit * 5, 50))
        .all()
    )
    ranked: list[dict[str, Any]] = []
    for job in rows:
        priority, evidence = candidate_priority(job, now=now)
        if evidence["days_remaining"] is not None and evidence["days_remaining"] < 0:
            ranked.append({
                "job": job,
                "priority_score": priority,
                "priority_evidence": evidence,
                "decision": {
                    "allowed": False,
                    "code": "posting_deadline_passed",
                    "reason": "The posting deadline has already passed.",
                    "metadata": {},
                },
            })
            continue
        decision = evaluate_unattended_job_policy(db, user, job, now=now)
        ranked.append({
            "job": job,
            "priority_score": priority,
            "priority_evidence": evidence,
            "decision": decision.to_dict(),
        })
    ranked.sort(
        key=lambda item: (
            bool(item["decision"].get("allowed")),
            item["priority_score"],
            int(item["job"].id or 0),
        ),
        reverse=True,
    )
    return ranked[:limit]


def build_scheduler_preview(db, user, *, candidate_limit: int = 20) -> dict[str, Any]:
    core = get_settings()
    operations = get_operations_settings()
    user_settings = scheduler_settings(user)
    user_decision = evaluate_autopilot_policy(db, user)
    discovery_policy_allowed = discovery_allowed_by_user_policy(user_decision)
    search_plan = build_search_plan(user)
    ranked = rank_scheduler_candidates(db, user, limit=candidate_limit)
    allowed = [item for item in ranked if item["decision"].get("allowed")]

    if not user_settings["scheduler_policy_current"]:
        scheduler_state = "policy_upgrade_required"
    elif not user_settings.get("auto_search_enabled") and not user_settings.get("auto_apply_enabled"):
        scheduler_state = "disabled"
    elif not operations.autopilot_enabled:
        scheduler_state = "globally_disabled"
    elif user_settings.get("auto_apply_enabled") and user_decision.allowed and allowed:
        scheduler_state = "autonomous_candidates_ready"
    elif (
        user_settings.get("auto_search_enabled")
        and discovery_policy_allowed
        and search_plan["ready"]
    ):
        scheduler_state = "discovery_ready"
    elif not user_decision.allowed:
        scheduler_state = "blocked"
    else:
        scheduler_state = "configuration_blocked"

    candidates = []
    for item in ranked:
        job = item["job"]
        candidates.append({
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "source": str(job.source.value if hasattr(job.source, "value") else job.source),
            "url": job.url,
            "relevance_score": float(job.relevance_score or 0.0),
            "priority_score": item["priority_score"],
            "priority_evidence": item["priority_evidence"],
            "policy_decision": item["decision"],
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scheduler_state": scheduler_state,
        "scheduler_policy_version": user_settings.get("scheduler_policy_version"),
        "scheduler_policy_current": user_settings["scheduler_policy_current"],
        "required_scheduler_policy_version": SCHEDULER_POLICY_VERSION,
        "global_autopilot_enabled": operations.autopilot_enabled,
        "global_kill_switch": operations.global_kill_switch,
        "real_submission_enabled": core.allow_real_application_submit,
        "required_adapter_maturity": REQUIRED_AUTONOMOUS_MATURITY,
        "platform_maturities": live_platform_maturities(),
        "user_policy": user_decision.to_dict(),
        "discovery_policy_allowed": discovery_policy_allowed,
        "search_plan": search_plan,
        "settings": user_settings,
        "summary": {
            "candidate_count": len(candidates),
            "allowed_candidate_count": len(allowed),
            "blocked_candidate_count": len(candidates) - len(allowed),
        },
        "candidates": candidates,
        "invariants": {
            "scheduler_defaults_off": SCHEDULER_DEFAULTS["auto_search_enabled"] is False,
            "auto_apply_defaults_off": SCHEDULER_DEFAULTS["auto_apply_enabled"] is False,
            "dry_run_defaults_on": SCHEDULER_DEFAULTS["dry_run_mode"] is True,
            "legacy_scheduler_flags_require_policy_upgrade": True,
            "no_hardcoded_search_identity": True,
            "application_caps_do_not_stop_discovery": True,
            "certified_autonomous_required": True,
            "worker_rechecks_policy_before_submission": True,
        },
    }
