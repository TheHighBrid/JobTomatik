"""Worker integration that prevents stale discovered jobs from being scheduled.

The core ranking service is also used by read-only API previews. Application execution,
however, occurs inside Celery workers through ``app.tasks.scraping``. This integration
wraps that worker-local ranking binding without changing the canonical policy service or
creating a second application scheduler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.discovery_scheduler import job_freshness_evidence


FRESHNESS_BLOCK_CODE = "posting_freshness_expired"
FRESHNESS_UNKNOWN_CODE = "posting_freshness_unknown"


def _source_value(job) -> str:
    source = getattr(job, "source", None)
    return str(getattr(source, "value", source) or "").strip().lower()


def _manual_without_discovery_provenance(job) -> bool:
    if _source_value(job) != "manual":
        return False
    raw = dict(getattr(job, "raw_data", None) or {})
    return not raw.get("discovery_first_seen_at") and not raw.get("discovery_last_seen_at")


def gate_ranked_candidates(
    ranked: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Attach freshness evidence and fail closed for stale discovered candidates."""

    gated: list[dict[str, Any]] = []
    for original in ranked:
        item = dict(original)
        job = item.get("job")
        priority_evidence = dict(item.get("priority_evidence") or {})
        decision = dict(item.get("decision") or {})

        if job is None:
            freshness = {
                "fresh": False,
                "reason": "freshness_unknown",
                "observed_at": None,
                "age_hours": None,
                "ttl_hours": None,
                "evidence_source": None,
            }
        elif _manual_without_discovery_provenance(job):
            freshness = {
                "fresh": True,
                "reason": "manual_not_subject_to_discovery_ttl",
                "observed_at": None,
                "age_hours": None,
                "ttl_hours": None,
                "evidence_source": "manual",
            }
        else:
            freshness = job_freshness_evidence(job, now=now)

        priority_evidence["discovery_freshness"] = freshness
        item["priority_evidence"] = priority_evidence

        if decision.get("allowed") and not freshness.get("fresh"):
            decision["allowed"] = False
            if freshness.get("reason") == "freshness_expired":
                decision["code"] = FRESHNESS_BLOCK_CODE
                decision["reason"] = "The posting has not been rediscovered within the freshness window."
            else:
                decision["code"] = FRESHNESS_UNKNOWN_CODE
                decision["reason"] = "The posting lacks current discovery freshness evidence."
            decision["metadata"] = {
                **dict(decision.get("metadata") or {}),
                "discovery_freshness": freshness,
            }
        item["decision"] = decision
        gated.append(item)

    gated.sort(
        key=lambda item: (
            bool((item.get("decision") or {}).get("allowed")),
            float(item.get("priority_score") or 0.0),
            int(getattr(item.get("job"), "id", 0) or 0),
        ),
        reverse=True,
    )
    if limit is not None:
        return gated[: max(0, int(limit))]
    return gated


def install_scheduler_freshness_gate() -> None:
    """Wrap the worker scheduler binding once and preserve the canonical ranker."""

    from app.tasks import scraping

    current = scraping.rank_scheduler_candidates
    if getattr(current, "_jobtomatik_discovery_freshness_gate", False):
        return

    original = current

    def ranked_with_freshness(db, user, *, limit: int = 20, now: datetime | None = None):
        requested = max(1, int(limit))
        expanded = min(500, max(requested, requested * 5))
        ranked = original(db, user, limit=expanded, now=now)
        return gate_ranked_candidates(ranked, now=now, limit=requested)

    ranked_with_freshness._jobtomatik_discovery_freshness_gate = True  # type: ignore[attr-defined]
    ranked_with_freshness._jobtomatik_original_ranker = original  # type: ignore[attr-defined]
    scraping.rank_scheduler_candidates = ranked_with_freshness


__all__ = [
    "FRESHNESS_BLOCK_CODE",
    "FRESHNESS_UNKNOWN_CODE",
    "gate_ranked_candidates",
    "install_scheduler_freshness_gate",
]
