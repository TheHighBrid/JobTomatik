"""Stable identities for discovered job listings.

Provider search pages often decorate the same listing URL with changing tracking
parameters. Persisted jobs must use the provider's posting identifier or a canonical
URL rather than those volatile parameters.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, urlsplit, urlunsplit


_LINKEDIN_JOB_ID = re.compile(r"/jobs/view/(?:[^/?#]*?-)?(?P<id>\d{6,})(?:/|$)", re.IGNORECASE)
_JOBBANK_JOB_ID = re.compile(
    r"/(?:jobsearch/jobposting|rechercheemplois/offredemploi)/(?P<id>\d+)",
    re.IGNORECASE,
)


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _source_value(value: Any) -> str:
    return _normalized(getattr(value, "value", value)).replace(" ", "_") or "unknown"


def provider_posting_id(
    source: Any,
    url: str,
    *,
    external_id: Optional[str] = None,
    raw_data: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Return a provider-stable posting ID when one can be proven."""
    source_name = _source_value(source)
    raw = dict(raw_data or {})
    candidates = [
        str(url or ""),
        str(raw.get("jobbank_original_url") or ""),
        str(raw.get("selected_apply_url") or ""),
    ]

    if source_name == "linkedin":
        for candidate in candidates:
            parsed = urlsplit(candidate)
            match = _LINKEDIN_JOB_ID.search(parsed.path or "")
            if match:
                return match.group("id")
            query = parse_qs(parsed.query)
            for key in ("currentJobId", "currentjobid"):
                value = (query.get(key) or [None])[0]
                if value and str(value).isdigit():
                    return str(value)
        if external_id and str(external_id).isdigit() and len(str(external_id)) >= 6:
            return str(external_id)

    if source_name == "indeed":
        for candidate in candidates:
            query = parse_qs(urlsplit(candidate).query)
            value = (query.get("jk") or [None])[0]
            if value:
                return str(value)
        if external_id and re.fullmatch(r"[a-zA-Z0-9_-]{8,}", str(external_id)):
            return str(external_id)

    if source_name == "jobbank":
        for candidate in candidates:
            match = _JOBBANK_JOB_ID.search(urlsplit(candidate).path or "")
            if match:
                return match.group("id")
        if external_id and str(external_id).isdigit():
            return str(external_id)

    return None


def canonical_job_url(
    source: Any,
    url: str,
    *,
    external_id: Optional[str] = None,
    raw_data: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return a tracking-free URL while preserving provider job identity."""
    source_name = _source_value(source)
    posting_id = provider_posting_id(
        source,
        url,
        external_id=external_id,
        raw_data=raw_data,
    )
    if source_name == "linkedin" and posting_id:
        return f"https://www.linkedin.com/jobs/view/{posting_id}"
    if source_name == "indeed" and posting_id:
        return f"https://ca.indeed.com/viewjob?jk={posting_id}"
    if source_name == "jobbank" and posting_id:
        return f"https://www.jobbank.gc.ca/jobsearch/jobposting/{posting_id}"

    parsed = urlsplit(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return str(url or "")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def job_identity_key(job: Mapping[str, Any]) -> str:
    """Build a stable identity from provider ID, canonical URL, or a bounded fallback."""
    source = job.get("source")
    source_name = _source_value(source)
    raw_data = job.get("raw_data") if isinstance(job.get("raw_data"), Mapping) else {}
    posting_id = provider_posting_id(
        source,
        str(job.get("url") or ""),
        external_id=str(job.get("external_id") or "") or None,
        raw_data=raw_data,
    )
    if posting_id:
        return f"{source_name}:posting:{posting_id}"

    canonical = canonical_job_url(
        source,
        str(job.get("url") or ""),
        external_id=str(job.get("external_id") or "") or None,
        raw_data=raw_data,
    )
    if canonical:
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return f"{source_name}:url:{digest}"

    fallback = "|".join(
        (
            source_name,
            _normalized(job.get("company")),
            _normalized(job.get("title")),
            _normalized(job.get("location")),
        )
    )
    digest = hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:24]
    return f"{source_name}:fallback:{digest}"


def stable_external_id(job: Mapping[str, Any]) -> str:
    """Return a deterministic value suitable for ``Job.external_id``."""
    source = job.get("source")
    posting_id = provider_posting_id(
        source,
        str(job.get("url") or ""),
        external_id=str(job.get("external_id") or "") or None,
        raw_data=job.get("raw_data") if isinstance(job.get("raw_data"), Mapping) else {},
    )
    if posting_id:
        return f"{_source_value(source)}:{posting_id}"
    existing = str(job.get("external_id") or "").strip()
    return existing or job_identity_key(job)


__all__ = [
    "canonical_job_url",
    "job_identity_key",
    "provider_posting_id",
    "stable_external_id",
]
