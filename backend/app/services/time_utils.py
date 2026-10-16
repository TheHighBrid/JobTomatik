"""Shared timezone-aware clock helpers.

SubmissionApproval and related models use DateTime(timezone=True).
All comparisons and writes must use aware UTC to avoid:
  TypeError: can't compare offset-naive and offset-aware datetimes
This was the concrete blocker on Affirm application #14 (2026-10-10).
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)
