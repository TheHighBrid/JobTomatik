"""Database-aware deduplication for repeated discovery searches."""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.job import Job
from app.services.job_identity import (
    canonical_job_url,
    job_identity_key,
    stable_external_id,
)


def _job_mapping(job: Job) -> dict[str, Any]:
    return {
        "external_id": job.external_id,
        "source": job.source,
        "url": job.url,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "raw_data": dict(job.raw_data or {}),
    }


def partition_new_discovery_jobs(
    db: Session,
    raw_jobs: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Normalize identities and collapse duplicates repeated within this search.

    A listing already persisted globally remains in the returned list, but its
    ``external_id`` is rebound to the existing row. The main discovery pipeline can
    then preserve its user-scoped evaluation and knowledge-graph behavior while
    correctly counting it as a duplicate. Only additional copies of the same listing
    within the current search are removed here.
    """
    existing_by_external: dict[str, Job] = {}
    existing_by_identity: dict[str, Job] = {}
    for existing in db.query(Job).all():
        if existing.external_id:
            existing_by_external[str(existing.external_id)] = existing
        existing_by_identity.setdefault(job_identity_key(_job_mapping(existing)), existing)

    prepared_jobs: list[dict[str, Any]] = []
    collapsed_duplicates = 0
    seen_run_identities: set[str] = set()
    seen_run_external_ids: set[str] = set()

    for raw_job in raw_jobs:
        normalized = dict(raw_job)
        normalized["raw_data"] = dict(normalized.get("raw_data") or {})
        normalized["external_id"] = stable_external_id(normalized)
        normalized["url"] = canonical_job_url(
            normalized.get("source"),
            str(normalized.get("url") or ""),
            external_id=str(normalized.get("external_id") or "") or None,
            raw_data=normalized["raw_data"],
        )
        identity = job_identity_key(normalized)
        external_id = str(normalized.get("external_id") or "")

        existing = existing_by_external.get(external_id) or existing_by_identity.get(identity)
        if existing is not None:
            normalized["external_id"] = existing.external_id
            external_id = str(existing.external_id or "")

        if external_id in seen_run_external_ids or identity in seen_run_identities:
            collapsed_duplicates += 1
            continue

        prepared_jobs.append(normalized)
        seen_run_external_ids.add(external_id)
        seen_run_identities.add(identity)

    return prepared_jobs, collapsed_duplicates


__all__ = ["partition_new_discovery_jobs"]
