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
    """Search existing boards plus explicitly configured official ATS tenants."""

    normalized_sources = _source_values(sources)
    targets: list[dict[str, str]] = []
    for target in ats_targets or []:
        try:
            normalized = normalize_target(target)
        except PublicATSDiscoveryError as exc:
            logger.warning("Ignoring invalid ATS target: %s", exc)
            continue
        if sources is None or normalized["provider"] in normalized_sources:
            targets.append(normalized)

    tasks: list[Any] = []
    broad_sources = [source for source in normalized_sources if source in BROAD_SOURCES]
    if broad_sources:
        tasks.append(
            search_broad_jobs(
                keywords=keywords,
                location=location,
                salary_min=salary_min,
                salary_max=salary_max,
                job_type=job_type,
                sources=broad_sources,
                limit=limit,
            )
        )

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

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    discovered: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Discovery source failed without aborting the search: %s", result)
            continue
        if isinstance(result, list):
            discovered.extend(item for item in result if isinstance(item, dict))

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

    return unique
