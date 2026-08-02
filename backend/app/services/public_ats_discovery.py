"""Targeted discovery for official public Greenhouse, Lever, and Ashby boards.

This module performs read-only JSON discovery. It never opens an application form,
starts an applicant session, or submits anything. Provider identifiers are explicitly
configured by the user so JobTomatik does not crawl arbitrary tenants.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

SUPPORTED_PUBLIC_ATS = {"greenhouse", "lever", "ashby"}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_RESPONSE_BYTES = 10_000_000


class PublicATSDiscoveryError(RuntimeError):
    """Raised when an official board cannot be safely queried or normalized."""


def normalize_target(target: dict[str, Any]) -> dict[str, str]:
    provider = str(target.get("provider") or "").strip().lower()
    identifier = str(target.get("identifier") or "").strip()
    company = str(target.get("company") or identifier).strip()

    if provider not in SUPPORTED_PUBLIC_ATS:
        raise PublicATSDiscoveryError(f"Unsupported public ATS provider: {provider or 'missing'}")
    if not identifier or not _IDENTIFIER.fullmatch(identifier):
        raise PublicATSDiscoveryError(
            "ATS identifier may contain only letters, numbers, underscores, and hyphens"
        )
    if not company:
        company = identifier
    return {"provider": provider, "identifier": identifier, "company": company[:255]}


def provider_request(target: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    normalized = normalize_target(target)
    identifier = quote(normalized["identifier"], safe="")
    if normalized["provider"] == "greenhouse":
        return (
            f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs",
            {"content": "true"},
        )
    if normalized["provider"] == "lever":
        return f"https://api.lever.co/v0/postings/{identifier}", {"mode": "json"}
    return f"https://api.ashbyhq.com/posting-api/job-board/{identifier}", None


def _strip_html(value: Any) -> str:
    if not value:
        return ""
    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def _query_tokens(value: str) -> list[str]:
    stop = {
        "and",
        "the",
        "for",
        "with",
        "full",
        "time",
        "remote",
        "canada",
        "ontario",
    }
    return [
        token
        for token in re.split(r"[^a-z0-9+#.]+", (value or "").lower())
        if len(token) >= 2 and token not in stop
    ]


def _matches(job: dict[str, Any], keywords: str, location: str | None) -> bool:
    haystack = " ".join(
        str(job.get(key) or "")
        for key in ("title", "company", "location", "description", "requirements")
    ).lower()
    tokens = _query_tokens(keywords)
    if tokens and not any(token in haystack for token in tokens):
        return False

    requested_location = (location or "").strip().lower()
    if requested_location:
        actual_location = str(job.get("location") or "").lower()
        location_tokens = _query_tokens(requested_location)
        if "remote" not in actual_location and location_tokens:
            if not any(token in actual_location for token in location_tokens):
                return False
    return True


def _external_id(provider: str, identifier: str, provider_id: Any, url: str) -> str:
    stable = str(provider_id or "").strip()
    if not stable:
        stable = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return f"{provider}:{identifier}:{stable}"


def _base_job(
    *,
    provider: str,
    identifier: str,
    company: str,
    provider_id: Any,
    title: str,
    location: str,
    url: str,
    description: str,
    requirements: str = "",
    job_type: str | None = None,
    posted_at: Any = None,
    api_url: str,
    provider_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not url:
        return None
    clean_title = str(title or "Untitled").strip()[:500]
    clean_company = str(company or identifier).strip()[:255]
    clean_location = str(location or "").strip()[:255]
    clean_description = str(description or "").strip()
    clean_requirements = str(requirements or "").strip()
    external_id = _external_id(provider, identifier, provider_id, url)

    return {
        "external_id": external_id,
        "title": clean_title,
        "company": clean_company,
        "location": clean_location,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "CAD",
        "job_type": job_type,
        "description": clean_description,
        "requirements": clean_requirements,
        "url": url,
        "source": provider,
        "posted_at": posted_at,
        "application_method": "external_url",
        "raw_data": {
            "official_public_ats": True,
            "ats_provider": provider,
            "ats_identifier": identifier,
            "ats_company": clean_company,
            "provider_api_url": api_url,
            "provider_job_id": str(provider_id or ""),
            "application_method": "external_url",
            "selected_apply_url": url,
            "discovery_provenance": "official_public_json_api",
            "provider_payload": provider_payload or {},
        },
    }


def normalize_greenhouse(
    payload: object,
    *,
    identifier: str,
    company: str,
    api_url: str,
    fallback_job_type: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise PublicATSDiscoveryError("Greenhouse returned an unexpected payload")

    result: list[dict[str, Any]] = []
    for item in payload["jobs"]:
        if not isinstance(item, dict):
            continue
        location = item.get("location") or {}
        location_name = location.get("name", "") if isinstance(location, dict) else str(location)
        job = _base_job(
            provider="greenhouse",
            identifier=identifier,
            company=company,
            provider_id=item.get("id"),
            title=item.get("title") or "Untitled",
            location=location_name,
            url=str(item.get("absolute_url") or ""),
            description=_strip_html(item.get("content")),
            job_type=fallback_job_type,
            posted_at=item.get("updated_at"),
            api_url=api_url,
            provider_payload={
                "departments": item.get("departments") or [],
                "offices": item.get("offices") or [],
                "metadata": item.get("metadata") or [],
            },
        )
        if job:
            result.append(job)
    return result


def normalize_lever(
    payload: object,
    *,
    identifier: str,
    company: str,
    api_url: str,
    fallback_job_type: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise PublicATSDiscoveryError("Lever returned an unexpected payload")

    result: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        categories = item.get("categories") or {}
        categories = categories if isinstance(categories, dict) else {}
        sections = []
        for section in item.get("lists") or []:
            if isinstance(section, dict):
                label = _strip_html(section.get("text"))
                content = _strip_html(section.get("content"))
                sections.append(f"{label}: {content}".strip(": "))
        description = item.get("descriptionPlain") or _strip_html(item.get("description"))
        requirements = " ".join(part for part in sections if part)
        commitment = str(categories.get("commitment") or "").lower()
        inferred_type = fallback_job_type
        if "part" in commitment:
            inferred_type = "part_time"
        elif "contract" in commitment or "temporary" in commitment:
            inferred_type = "contract"
        elif "intern" in commitment:
            inferred_type = "internship"
        elif "full" in commitment:
            inferred_type = "full_time"

        job = _base_job(
            provider="lever",
            identifier=identifier,
            company=company,
            provider_id=item.get("id"),
            title=item.get("text") or "Untitled",
            location=str(categories.get("location") or ""),
            url=str(item.get("hostedUrl") or item.get("applyUrl") or ""),
            description=str(description or ""),
            requirements=requirements,
            job_type=inferred_type,
            posted_at=item.get("createdAt"),
            api_url=api_url,
            provider_payload={
                "categories": categories,
                "workplace_type": item.get("workplaceType"),
            },
        )
        if job:
            result.append(job)
    return result


def normalize_ashby(
    payload: object,
    *,
    identifier: str,
    company: str,
    api_url: str,
    fallback_job_type: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise PublicATSDiscoveryError("Ashby returned an unexpected payload")

    result: list[dict[str, Any]] = []
    for item in payload["jobs"]:
        if not isinstance(item, dict):
            continue
        employment_type = str(item.get("employmentType") or "").lower()
        inferred_type = fallback_job_type
        if "part" in employment_type:
            inferred_type = "part_time"
        elif "contract" in employment_type or "temporary" in employment_type:
            inferred_type = "contract"
        elif "intern" in employment_type:
            inferred_type = "internship"
        elif "full" in employment_type:
            inferred_type = "full_time"

        job = _base_job(
            provider="ashby",
            identifier=identifier,
            company=company,
            provider_id=item.get("id"),
            title=item.get("title") or "Untitled",
            location=str(item.get("location") or ""),
            url=str(item.get("jobUrl") or item.get("applyUrl") or ""),
            description=_strip_html(item.get("descriptionHtml") or item.get("description")),
            job_type=inferred_type,
            posted_at=item.get("publishedAt") or item.get("updatedAt"),
            api_url=api_url,
            provider_payload={
                "department": item.get("department"),
                "team": item.get("team"),
                "is_remote": item.get("isRemote"),
                "employment_type": item.get("employmentType"),
            },
        )
        if job:
            result.append(job)
    return result


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str] | None,
) -> object:
    response = await client.get(url, params=params)
    response.raise_for_status()
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise PublicATSDiscoveryError("Provider response exceeded 10 MB")
    try:
        return response.json()
    except ValueError as exc:
        raise PublicATSDiscoveryError("Provider returned invalid JSON") from exc


async def discover_public_ats_target(
    target: dict[str, Any],
    *,
    keywords: str,
    location: str | None,
    job_type: str | None,
    limit: int,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Discover matching jobs from one explicitly configured official board."""

    normalized = normalize_target(target)
    url, params = provider_request(normalized)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "JobTomatik/2 public-ats-discovery"},
        )

    try:
        payload = await _fetch_json(client, url, params)
        common = {
            "identifier": normalized["identifier"],
            "company": normalized["company"],
            "api_url": url,
            "fallback_job_type": job_type,
        }
        if normalized["provider"] == "greenhouse":
            jobs = normalize_greenhouse(payload, **common)
        elif normalized["provider"] == "lever":
            jobs = normalize_lever(payload, **common)
        else:
            jobs = normalize_ashby(payload, **common)

        matches = [job for job in jobs if _matches(job, keywords, location)]
        return matches[: max(1, min(int(limit), 100))]
    except (httpx.HTTPError, PublicATSDiscoveryError) as exc:
        raise PublicATSDiscoveryError(
            f"{normalized['provider']} discovery failed for {normalized['identifier']}: {exc}"
        ) from exc
    finally:
        if owns_client:
            await client.aclose()
