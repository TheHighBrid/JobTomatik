from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.models.application import (
    Application,
    ApplicationEvent,
    ApplicationTargetStatus,
)
from app.models.job import Job


_LINKEDIN_DOMAINS = ("linkedin.com",)
_JOB_BANK_DOMAINS = ("jobbank.gc.ca", "guichetemplois.gc.ca")
_LINKEDIN_LISTING_PATHS = ("/jobs/view/", "/jobs/collections/")
_JOB_BANK_LISTING_PATHS = ("/jobsearch/jobposting/", "/rechercheemplois/offredemploi/")


def _host_matches(hostname: str, domains: tuple[str, ...]) -> bool:
    host = (hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def is_listing_source(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if _host_matches(host, _LINKEDIN_DOMAINS):
        return any(fragment in path for fragment in _LINKEDIN_LISTING_PATHS)
    if _host_matches(host, _JOB_BANK_DOMAINS):
        return any(fragment in path for fragment in _JOB_BANK_LISTING_PATHS)
    return False


def is_valid_application_target(source_url: str, target_url: str) -> bool:
    parsed = urlparse(target_url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if is_listing_source(target_url):
        return False
    source_host = (urlparse(source_url or "").hostname or "").lower()
    target_host = (parsed.hostname or "").lower()
    if source_host and target_host == source_host and is_listing_source(source_url):
        return False
    return True


def _event(
    db,
    app: Application,
    event_type: str,
    *,
    from_status: Optional[str],
    to_status: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(ApplicationEvent(
        application_id=app.id,
        event_type=event_type,
        from_state=from_status,
        to_state=to_status,
        payload=payload or {},
    ))


def initialize_application_target(db, app: Application, job: Job) -> Optional[str]:
    source_url = (app.source_listing_url or job.url or "").strip()
    if source_url and not app.source_listing_url:
        app.source_listing_url = source_url

    if app.application_target_url and is_valid_application_target(
        source_url,
        app.application_target_url,
    ):
        app.application_target_status = ApplicationTargetStatus.resolved.value
        return app.application_target_url

    if source_url and not is_listing_source(source_url):
        previous = app.application_target_status or ApplicationTargetStatus.unresolved.value
        app.application_target_url = source_url
        app.application_target_status = ApplicationTargetStatus.resolved.value
        app.application_target_resolved_at = app.application_target_resolved_at or datetime.utcnow()
        app.application_target_metadata = {
            **dict(app.application_target_metadata or {}),
            "resolution_method": "direct_job_url",
        }
        if previous != ApplicationTargetStatus.resolved.value:
            _event(
                db,
                app,
                "application_target_initialized",
                from_status=previous,
                to_status=ApplicationTargetStatus.resolved.value,
                payload={"source_listing_url": source_url, "application_target_url": source_url},
            )
        return source_url

    if not app.application_target_status:
        app.application_target_status = ApplicationTargetStatus.unresolved.value
    return None


def mark_target_resolving(db, app: Application, *, source_url: str) -> None:
    previous = app.application_target_status or ApplicationTargetStatus.unresolved.value
    app.source_listing_url = app.source_listing_url or source_url
    app.application_target_status = ApplicationTargetStatus.resolving.value
    _event(
        db,
        app,
        "application_target_resolution_started",
        from_status=previous,
        to_status=ApplicationTargetStatus.resolving.value,
        payload={"source_listing_url": source_url},
    )


def record_application_target(
    db,
    app: Application,
    *,
    target_url: str,
    method: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    source_url = app.source_listing_url or ""
    if not is_valid_application_target(source_url, target_url):
        raise ValueError("Resolved application target is not a valid employer or ATS URL.")
    previous = app.application_target_status or ApplicationTargetStatus.unresolved.value
    app.application_target_url = target_url
    app.application_target_status = ApplicationTargetStatus.resolved.value
    app.application_target_resolved_at = datetime.utcnow()
    app.application_target_metadata = {
        **dict(app.application_target_metadata or {}),
        **dict(metadata or {}),
        "resolution_method": method,
    }
    _event(
        db,
        app,
        "application_target_resolved",
        from_status=previous,
        to_status=ApplicationTargetStatus.resolved.value,
        payload={
            "source_listing_url": source_url,
            "application_target_url": target_url,
            "resolution_method": method,
        },
    )
    return target_url


def record_target_requires_human(
    db,
    app: Application,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    previous = app.application_target_status or ApplicationTargetStatus.unresolved.value
    app.application_target_status = ApplicationTargetStatus.requires_human.value
    app.application_target_metadata = {
        **dict(app.application_target_metadata or {}),
        **dict(metadata or {}),
    }
    _event(
        db,
        app,
        "application_target_requires_human",
        from_status=previous,
        to_status=ApplicationTargetStatus.requires_human.value,
        payload=dict(metadata or {}),
    )


def record_target_failure(
    db,
    app: Application,
    *,
    error: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    previous = app.application_target_status or ApplicationTargetStatus.unresolved.value
    app.application_target_status = ApplicationTargetStatus.failed.value
    app.application_target_metadata = {
        **dict(app.application_target_metadata or {}),
        **dict(metadata or {}),
        "last_error": error[:500],
    }
    _event(
        db,
        app,
        "application_target_resolution_failed",
        from_status=previous,
        to_status=ApplicationTargetStatus.failed.value,
        payload={"error": error[:500], **dict(metadata or {})},
    )


def target_url_for_application(app: Application, job: Job) -> Optional[str]:
    source_url = app.source_listing_url or job.url or ""
    target_url = app.application_target_url or ""
    if is_valid_application_target(source_url, target_url):
        return target_url
    if source_url and not is_listing_source(source_url):
        return source_url
    return None