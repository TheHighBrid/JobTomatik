"""Continuous discovery health, backoff, and freshness policy.

Discovery is read-only and remains separate from application autonomy. This module
uses retained per-source diagnostics to avoid hammering an unhealthy provider and
records a bounded freshness contract for scheduler candidates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.models.intelligence import AgentRun


DISCOVERY_POLICY_VERSION = "continuous-discovery-v1"
DISCOVERY_FRESHNESS_TTL_HOURS = 72
SOURCE_BACKOFF_BASE_SECONDS = 15 * 60
SOURCE_BACKOFF_MAX_SECONDS = 6 * 60 * 60
SOURCE_HISTORY_LIMIT = 60
BROAD_DISCOVERY_SOURCES = frozenset({"indeed", "linkedin", "jobbank", "glassdoor"})


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def source_health_key(*, source: str, kind: str, target: str | None = None) -> str:
    source_value = _normalized(source) or "unknown"
    kind_value = _normalized(kind) or "unknown"
    target_value = _normalized(target)
    return f"{kind_value}:{source_value}:{target_value or '*'}"


def _matching_diagnostic(
    run: AgentRun,
    *,
    source: str,
    kind: str,
    target: str | None,
) -> Mapping[str, Any] | None:
    result = run.result if isinstance(run.result, dict) else {}
    diagnostics = result.get("source_diagnostics")
    if not isinstance(diagnostics, list):
        return None
    expected_source = _normalized(source)
    expected_kind = _normalized(kind)
    expected_target = _normalized(target)
    for item in diagnostics:
        if not isinstance(item, Mapping):
            continue
        if _normalized(item.get("source")) != expected_source:
            continue
        if _normalized(item.get("kind")) != expected_kind:
            continue
        if _normalized(item.get("target")) != expected_target:
            continue
        return item
    return None


def source_backoff_status(
    db: Session,
    *,
    user_id: int,
    source: str,
    kind: str,
    target: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return fail-soft exponential backoff derived from retained diagnostics.

    Only a contiguous tail of failures counts. A later success resets the failure
    streak. The maximum cooldown is six hours, matching the historical discovery
    cadence while allowing the new hourly scheduler to probe healthy sources more
    frequently without repeatedly hammering an unhealthy source.
    """

    current = _aware(now) or _utc_now()
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == int(user_id))
        .order_by(AgentRun.id.desc())
        .limit(SOURCE_HISTORY_LIMIT)
        .all()
    )
    consecutive_failures = 0
    last_failure_at: datetime | None = None
    last_status: str | None = None

    for run in runs:
        diagnostic = _matching_diagnostic(
            run,
            source=source,
            kind=kind,
            target=target,
        )
        if diagnostic is None:
            continue
        status = _normalized(diagnostic.get("status"))
        observed_at = _aware(run.completed_at or run.updated_at or run.created_at)
        if last_status is None:
            last_status = status or None
        if status == "success":
            break
        if status != "failed":
            continue
        consecutive_failures += 1
        if last_failure_at is None and observed_at is not None:
            last_failure_at = observed_at

    cooldown_seconds = 0
    retry_at: datetime | None = None
    blocked = False
    if consecutive_failures and last_failure_at is not None:
        cooldown_seconds = min(
            SOURCE_BACKOFF_MAX_SECONDS,
            SOURCE_BACKOFF_BASE_SECONDS * (2 ** (consecutive_failures - 1)),
        )
        retry_at = last_failure_at + timedelta(seconds=cooldown_seconds)
        blocked = current < retry_at

    return {
        "key": source_health_key(source=source, kind=kind, target=target),
        "source": _normalized(source),
        "kind": _normalized(kind),
        "target": str(target).strip() if target else None,
        "last_status": last_status,
        "consecutive_failures": consecutive_failures,
        "cooldown_seconds": cooldown_seconds,
        "last_failure_at": last_failure_at.isoformat() if last_failure_at else None,
        "retry_at": retry_at.isoformat() if retry_at else None,
        "blocked": blocked,
    }


def apply_source_backoff(
    db: Session,
    *,
    user_id: int,
    search_params: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Filter a search plan down to sources/targets that are not cooling down."""

    params = dict(search_params or {})
    requested_sources = list(
        dict.fromkeys(
            _normalized(item)
            for item in (params.get("sources") or [])
            if _normalized(item)
        )
    )
    requested_targets = [
        dict(item)
        for item in (params.get("ats_targets") or [])
        if isinstance(item, Mapping)
    ]

    active_broad: list[str] = []
    active_targets: list[dict[str, Any]] = []
    blocked_sources: list[dict[str, Any]] = []

    for source in requested_sources:
        if source not in BROAD_DISCOVERY_SOURCES:
            continue
        health = source_backoff_status(
            db,
            user_id=user_id,
            source=source,
            kind="broad_board",
            target=None,
            now=now,
        )
        if health["blocked"]:
            blocked_sources.append(health)
        else:
            active_broad.append(source)

    for target in requested_targets:
        provider = _normalized(target.get("provider"))
        identifier = str(target.get("identifier") or "").strip()
        if not provider or not identifier:
            # Invalid targets are left to the existing normalization boundary so the
            # diagnostic remains attributable rather than disappearing silently here.
            active_targets.append(target)
            continue
        health = source_backoff_status(
            db,
            user_id=user_id,
            source=provider,
            kind="public_ats",
            target=identifier,
            now=now,
        )
        if health["blocked"]:
            blocked_sources.append(health)
        else:
            active_targets.append(target)

    active_target_providers = {
        _normalized(item.get("provider")) for item in active_targets if item.get("provider")
    }
    adjusted_sources = [
        source
        for source in requested_sources
        if source in active_broad or source in active_target_providers
    ]
    active_task_count = len(active_broad) + len(active_targets)
    adjusted = {
        **params,
        "sources": adjusted_sources,
        "ats_targets": active_targets,
    }
    return {
        "policy_version": DISCOVERY_POLICY_VERSION,
        "ready": active_task_count > 0,
        "search_params": adjusted,
        "requested_task_count": len(
            [source for source in requested_sources if source in BROAD_DISCOVERY_SOURCES]
        ) + len(requested_targets),
        "active_task_count": active_task_count,
        "blocked_sources": blocked_sources,
    }


def parse_discovery_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed)


def job_freshness_evidence(job, *, now: datetime | None = None) -> dict[str, Any]:
    """Return bounded freshness evidence for a persisted scheduler candidate."""

    current = _aware(now) or _utc_now()
    raw = dict(getattr(job, "raw_data", None) or {})
    observed = parse_discovery_timestamp(raw.get("discovery_last_seen_at"))
    source = "discovery_last_seen_at"
    if observed is None:
        observed = _aware(getattr(job, "updated_at", None))
        source = "updated_at"
    if observed is None:
        observed = _aware(getattr(job, "created_at", None))
        source = "created_at"
    if observed is None:
        return {
            "fresh": False,
            "reason": "freshness_unknown",
            "observed_at": None,
            "age_hours": None,
            "ttl_hours": DISCOVERY_FRESHNESS_TTL_HOURS,
            "evidence_source": None,
        }

    age_hours = max(0.0, (current - observed).total_seconds() / 3600.0)
    fresh = age_hours <= DISCOVERY_FRESHNESS_TTL_HOURS
    return {
        "fresh": fresh,
        "reason": "fresh" if fresh else "freshness_expired",
        "observed_at": observed.isoformat(),
        "age_hours": round(age_hours, 2),
        "ttl_hours": DISCOVERY_FRESHNESS_TTL_HOURS,
        "evidence_source": source,
    }


__all__ = [
    "BROAD_DISCOVERY_SOURCES",
    "DISCOVERY_FRESHNESS_TTL_HOURS",
    "DISCOVERY_POLICY_VERSION",
    "SOURCE_BACKOFF_BASE_SECONDS",
    "SOURCE_BACKOFF_MAX_SECONDS",
    "apply_source_backoff",
    "job_freshness_evidence",
    "parse_discovery_timestamp",
    "source_backoff_status",
    "source_health_key",
]
