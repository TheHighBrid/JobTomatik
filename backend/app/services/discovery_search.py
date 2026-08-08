"""Unified discovery entrypoint for broad boards and targeted public ATS APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.job_scraper import search_jobs as search_broad_jobs
from app.services.public_ats_discovery import (
    SUPPORTED_PUBLIC_ATS,
    PublicATSDiscoveryError,
    discover_public_ats_target,
    normalize_target,
)

logger = logging.getLogger(__name__)
BROAD_SOURCES = {"indeed", "linkedin", "jobbank", "glassdoor"}


def _source_values(sources: list[Any] | None) -> list[str]:
    if sources is None:
        return ["indeed", "linkedin", "jobbank"]
    if not sources:
        return []
    return list(
        dict.fromkeys(
            str(getattr(source, "value", source)).strip().lower()
            for source in sources
            if str(getattr(source, "value", source)).strip()
        )
    )


def _diagnostic(
    *,
    source: str,
    kind: str,
    status: str,
    result_count: int = 0,
    target: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Return bounded source telemetry without exception text or credentials."""
    return {
        "source": str(source or "unknown").strip().lower(),
        "kind": kind,
        "status": status,
        "result_count": max(0, int(result_count or 0)),
        "target": str(target).strip()[:180] if target else None,
        "error_code": str(error_code).strip().lower()[:100] if error_code else None,
    }


async def search_jobs_with_diagnostics(
    keywords: str,
    location: str | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    job_type: str | None = None,
    sources: list[str] | None = None,
    ats_targets: list[dict[str, Any]] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search configured sources and return jobs plus safe per-source telemetry.

    A single source failure never aborts the remaining search. Diagnostics deliberately
    omit raw exception messages because provider libraries can include request URLs or
    other sensitive runtime detail in exception strings.
    """

    normalized_sources = _source_values(sources)
    targets: list[dict[str, str]] = []
    diagnostics: list[dict[str, Any]] = []
    for target in ats_targets or []:
        try:
            normalized = normalize_target(target)
        except PublicATSDiscoveryError:
            diagnostics.append(_diagnostic(
                source="ats_target",
                kind="public_ats",
                status="failed",
                error_code="invalid_target",
            ))
            logger.warning("Ignoring invalid ATS target")
            continue
        if sources is None or normalized["provider"] in normalized_sources:
            targets.append(normalized)

    tasks: list[Any] = []
    task_meta: list[dict[str, Any]] = []

    # Run broad boards independently so one provider outage is observable rather than
    # collapsing several providers into one opaque aggregate failure.
    for source in normalized_sources:
        if source not in BROAD_SOURCES:
            continue
        tasks.append(
            search_broad_jobs(
                keywords=keywords,
                location=location,
                salary_min=salary_min,
                salary_max=salary_max,
                job_type=job_type,
                sources=[source],
                limit=limit,
            )
        )
        task_meta.append({"source": source, "kind": "broad_board", "target": None})

    target_limit = max(1, min(50, limit // max(len(targets), 1) + 1))
    for target in targets:
        tasks.append(
            discover_public_ats_target(
                target,
                keywords=keywords,
                location=location,
                job_type=job_type,
                limit=target_limit,
            )
        )
        task_meta.append({
            "source": target["provider"],
            "kind": "public_ats",
            "target": target.get("identifier"),
        })

    if not tasks:
        return {"jobs": [], "source_diagnostics": diagnostics}

    results = await asyncio.gather(*tasks, return_exceptions=True)
    discovered: list[dict[str, Any]] = []
    for meta, result in zip(task_meta, results):
        if isinstance(result, Exception):
            error_code = type(result).__name__.lower()
            diagnostics.append(_diagnostic(
                source=meta["source"],
                kind=meta["kind"],
                status="failed",
                target=meta.get("target"),
                error_code=error_code,
            ))
            logger.warning("Discovery source %s failed: %s", meta["source"], error_code)
            continue
        rows = [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []
        diagnostics.append(_diagnostic(
            source=meta["source"],
            kind=meta["kind"],
            status="success",
            target=meta.get("target"),
            result_count=len(rows),
        ))
        discovered.extend(rows)

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for job in discovered:
        external_id = str(job.get("external_id") or "").strip()
        source = str(job.get("source") or "manual").strip().lower()
        url = str(job.get("url") or "").strip()
        key = external_id or f"{source}:{url}"
        if not key or key in seen:
            continue
        seen.add(key)
        raw = dict(job.get("raw_data") or {})
        raw.setdefault("discovery_source", source)
        raw.setdefault("official_public_ats", source in SUPPORTED_PUBLIC_ATS)
        job["raw_data"] = raw
        unique.append(job)
        if len(unique) >= limit:
            break

    return {"jobs": unique, "source_diagnostics": diagnostics}


async def search_jobs(
    keywords: str,
    location: str | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    job_type: str | None = None,
    sources: list[str] | None = None,
    ats_targets: list[dict[str, Any]] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Compatibility entrypoint returning only discovered jobs."""

    result = await search_jobs_with_diagnostics(
        keywords=keywords,
        location=location,
        salary_min=salary_min,
        salary_max=salary_max,
        job_type=job_type,
        sources=sources,
        ats_targets=ats_targets,
        limit=limit,
    )
    return list(result["jobs"])
