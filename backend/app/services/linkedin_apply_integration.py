"""Compatibility bridge for LinkedIn jobs saved before browser apply routing.

Older discovery records store ``unsupported_job_board`` in ``Job.raw_data``.
The submission task trusts that cached method and therefore never reaches the
browser navigator. This worker integration clears only that stale LinkedIn
classification so the normal resolver can route the listing through the
outbound employer Apply link.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Dict

from app.services.apply_resolver import is_browser_resolvable_job_board_url


def _needs_linkedin_reresolution(job: Any) -> bool:
    raw: Dict[str, Any] = dict(getattr(job, "raw_data", None) or {})
    return (
        raw.get("application_method") == "unsupported_job_board"
        and is_browser_resolvable_job_board_url(getattr(job, "url", "") or "")
    )


def install_linkedin_apply_resolution() -> None:
    """Patch the worker's cached-method helper once, without changing task APIs."""
    import app.tasks.applications as applications_module

    original = applications_module._ensure_application_method
    if getattr(original, "_jobtomatik_linkedin_apply_resolution", False):
        return

    @wraps(original)
    def resolve_cached_linkedin_method(job: Any):
        if _needs_linkedin_reresolution(job):
            raw = dict(job.raw_data or {})
            raw.pop("application_method", None)
            raw.pop("selected_apply_url", None)
            raw["previous_application_method"] = "unsupported_job_board"
            raw["reason"] = "Re-resolving LinkedIn listing through outbound Apply navigation"
            job.raw_data = raw
        return original(job)

    resolve_cached_linkedin_method._jobtomatik_linkedin_apply_resolution = True
    applications_module._ensure_application_method = resolve_cached_linkedin_method


__all__ = ["install_linkedin_apply_resolution"]
