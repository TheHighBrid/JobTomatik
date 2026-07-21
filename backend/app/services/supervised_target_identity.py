"""Exact ATS target identity for supervised approval and browser execution.

This module performs read-only public metadata inspection. It never submits an
application and never bypasses authentication, CAPTCHA, MFA, or anti-bot controls.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from app.models.job import Job
from app.services.ats_lever import (
    fetch_lever_posting,
    inspect_lever_posting,
    parse_lever_job_url,
)
from app.services.operations_policy import platform_key_for_url
from app.services.supervised_platforms import (
    LEVER_PLATFORM_KEY,
    get_supervised_platform_policy,
)


_PERSISTED_KEY = "supervised_target_metadata"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_title(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _lever_adapter_version() -> str:
    policy = get_supervised_platform_policy(LEVER_PLATFORM_KEY)
    return policy.adapter_version if policy else "unknown"


def target_url_for_job(job: Job) -> str:
    raw = dict(job.raw_data or {})
    return str(raw.get("selected_apply_url") or job.url or "").strip()


def canonical_lever_apply_url(site: str, posting_id: str, region: str) -> str:
    host = "jobs.eu.lever.co" if region == "eu" else "jobs.lever.co"
    return f"https://{host}/{site}/{posting_id}/apply"


def _safe_official_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": payload.get("id"),
        "text": payload.get("text"),
        "hostedUrl": payload.get("hostedUrl"),
        "applyUrl": payload.get("applyUrl"),
        "categories": payload.get("categories") or {},
    }


def _invalid_lever_identity(
    *,
    target_url: str,
    blockers: list[str],
    site: Optional[str] = None,
    posting_id: Optional[str] = None,
    region: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "platform": LEVER_PLATFORM_KEY,
        "adapter": LEVER_PLATFORM_KEY,
        "adapter_version": _lever_adapter_version(),
        "verified": False,
        "blockers": blockers,
        "target_url": target_url,
        "canonical_application_url": None,
        "site": site,
        "posting_id": posting_id,
        "region": region,
        "official_title": None,
        "title_matches_local_job": False,
        "posting_metadata_hash": None,
        "identity_hash": None,
        "verification_error": error,
        "verified_at": None,
    }


async def resolve_supervised_target_metadata(job: Job) -> Dict[str, Any]:
    """Resolve exact public target identity for platforms that require it."""

    target_url = target_url_for_job(job)
    platform = platform_key_for_url(target_url)
    if platform != LEVER_PLATFORM_KEY:
        return {}

    site, posting_id, region = parse_lever_job_url(target_url)
    if not site or not posting_id:
        return _invalid_lever_identity(
            target_url=target_url,
            blockers=["lever_target_url_invalid"],
            site=site,
            posting_id=posting_id,
            region=region,
        )

    try:
        official = await fetch_lever_posting(site, posting_id, region=region)
    except Exception as exc:
        return _invalid_lever_identity(
            target_url=target_url,
            blockers=["lever_official_metadata_unavailable"],
            site=site,
            posting_id=posting_id,
            region=region,
            error=f"{type(exc).__name__}: {str(exc)[:300]}",
        )

    inspected = inspect_lever_posting(official)
    official_site = str(inspected.get("site") or "")
    official_region = str(inspected.get("region") or "")
    official_posting_id = str(inspected.get("posting_id") or "")
    official_title = str(inspected.get("title") or "").strip()
    canonical_url = canonical_lever_apply_url(site, posting_id, region)

    blockers: list[str] = []
    if not inspected.get("posting_metadata_certified"):
        blockers.append("lever_official_metadata_unverified")
    if official_site != site or official_posting_id != posting_id or official_region != region:
        blockers.append("lever_target_identity_mismatch")
    title_matches = _normalized_title(official_title) == _normalized_title(job.title)
    if not title_matches:
        blockers.append("lever_role_metadata_mismatch")

    official_payload = _safe_official_payload(official)
    posting_metadata_hash = _hash_value(official_payload)
    identity_payload = {
        "platform": LEVER_PLATFORM_KEY,
        "adapter": LEVER_PLATFORM_KEY,
        "adapter_version": _lever_adapter_version(),
        "site": site,
        "posting_id": posting_id,
        "region": region,
        "canonical_application_url": canonical_url,
        "posting_metadata_hash": posting_metadata_hash,
    }
    identity_hash = _hash_value(identity_payload)

    return {
        **identity_payload,
        "verified": not blockers,
        "blockers": blockers,
        "target_url": target_url,
        "official_title": official_title,
        "title_matches_local_job": title_matches,
        "posting_metadata_hash": posting_metadata_hash,
        "identity_hash": identity_hash,
        "verification_error": None,
        "verified_at": datetime.utcnow().isoformat(),
    }


async def verify_supervised_browser_target(
    *,
    current_url: str,
    adapter_name: str,
    adapter_version: str,
    expected_metadata: Optional[Mapping[str, Any]],
    refresh_official_metadata: bool,
    allow_same_site_confirmation: bool = False,
) -> Dict[str, Any]:
    """Verify that a live browser still represents the explicitly approved target."""

    expected = dict(expected_metadata or {})
    if not expected:
        return {
            "verified": True,
            "blockers": [],
            "platform": None,
            "current_url": current_url,
            "target_lock_required": False,
        }

    platform = str(expected.get("platform") or "").strip().lower()
    if platform != LEVER_PLATFORM_KEY:
        return {
            "verified": True,
            "blockers": [],
            "platform": platform,
            "current_url": current_url,
            "target_lock_required": False,
        }

    blockers: list[str] = []
    if str(adapter_name or "").strip().lower() != LEVER_PLATFORM_KEY:
        blockers.append("lever_runtime_adapter_mismatch")
    if str(adapter_version or "").strip() != str(expected.get("adapter_version") or "").strip():
        blockers.append("lever_runtime_adapter_version_mismatch")

    expected_site = str(expected.get("site") or "")
    expected_posting_id = str(expected.get("posting_id") or "")
    expected_region = str(expected.get("region") or "")
    observed_site, observed_posting_id, observed_region = parse_lever_job_url(current_url)

    parsed = urlparse(current_url or "")
    path_parts = [part for part in parsed.path.split("/") if part]
    same_site_confirmation = bool(
        allow_same_site_confirmation
        and path_parts
        and path_parts[0] == expected_site
        and observed_region == expected_region
    )
    if observed_site != expected_site or observed_region != expected_region:
        blockers.append("lever_runtime_site_or_region_mismatch")
    if observed_posting_id != expected_posting_id and not same_site_confirmation:
        blockers.append("lever_runtime_posting_mismatch")

    observed_metadata_hash = None
    if refresh_official_metadata and not blockers:
        try:
            official = await fetch_lever_posting(
                expected_site,
                expected_posting_id,
                region=expected_region,
            )
            inspected = inspect_lever_posting(official)
            observed_metadata_hash = _hash_value(_safe_official_payload(official))
            if not inspected.get("posting_metadata_certified"):
                blockers.append("lever_runtime_official_metadata_unverified")
            if observed_metadata_hash != str(expected.get("posting_metadata_hash") or ""):
                blockers.append("lever_runtime_official_metadata_changed")
        except Exception as exc:
            blockers.append("lever_runtime_official_metadata_unavailable")
            verification_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        else:
            verification_error = None
    else:
        verification_error = None

    return {
        "verified": not blockers,
        "blockers": blockers,
        "platform": platform,
        "current_url": current_url,
        "target_lock_required": True,
        "expected_site": expected_site,
        "expected_posting_id": expected_posting_id,
        "expected_region": expected_region,
        "observed_site": observed_site,
        "observed_posting_id": observed_posting_id,
        "observed_region": observed_region,
        "expected_metadata_hash": expected.get("posting_metadata_hash"),
        "observed_metadata_hash": observed_metadata_hash,
        "same_site_confirmation_allowed": same_site_confirmation,
        "verification_error": verification_error,
    }


def persisted_supervised_target_metadata(job: Job) -> Dict[str, Any]:
    raw = dict(job.raw_data or {})
    value = raw.get(_PERSISTED_KEY)
    return dict(value) if isinstance(value, dict) else {}


def persist_supervised_target_metadata(job: Job, metadata: Mapping[str, Any]) -> None:
    raw = dict(job.raw_data or {})
    raw[_PERSISTED_KEY] = dict(metadata)
    job.raw_data = raw


def target_identity_hash(metadata: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not metadata:
        return None
    value = str(metadata.get("identity_hash") or "").strip()
    return value or None


__all__ = [
    "canonical_lever_apply_url",
    "persist_supervised_target_metadata",
    "persisted_supervised_target_metadata",
    "resolve_supervised_target_metadata",
    "target_identity_hash",
    "target_url_for_job",
    "verify_supervised_browser_target",
]
