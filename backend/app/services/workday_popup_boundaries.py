"""Extend Workday manual-boundary detection across pages in one browser context.

Workday Candidate Experience may open sign-in or candidate-account creation in a new
tab after the bounded Apply action. The donor adapter treats both as human boundaries.
This integration scans only pages already created by the same browser context and never
enters credentials, creates an account, or interacts with a challenge.
"""

from __future__ import annotations

from typing import Any, Optional, Dict

from app.services import workday_challenge


_ORIGINAL_DETECT = workday_challenge.detect_workday_login_or_account_boundary


async def _detect_across_context(page: Any) -> Optional[Dict[str, Any]]:
    candidates = [page]
    try:
        for candidate in page.context.pages:
            if candidate not in candidates:
                candidates.append(candidate)
    except Exception:
        pass

    for candidate in reversed(candidates):
        try:
            result = await _ORIGINAL_DETECT(candidate)
        except Exception:
            continue
        if not result:
            continue
        details = dict(result.get("details") or {})
        details.update({
            "active_url": str(getattr(candidate, "url", "") or ""),
            "context_page_count": len(candidates),
            "credentials_entered": False,
            "account_created": False,
            "bypass_attempted": False,
        })
        return {**result, "details": details}
    return None


def install_workday_popup_boundary_detection() -> None:
    current = workday_challenge.detect_workday_login_or_account_boundary
    if getattr(current, "_jobtomatik_context_pages", False):
        return
    _detect_across_context._jobtomatik_context_pages = True
    workday_challenge.detect_workday_login_or_account_boundary = _detect_across_context


__all__ = ["install_workday_popup_boundary_detection"]
