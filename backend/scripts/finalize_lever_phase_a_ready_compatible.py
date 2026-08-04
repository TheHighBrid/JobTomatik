#!/usr/bin/env python3
"""Run the ordinary Lever finalizer with safe title punctuation compatibility."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts import finalize_lever_phase_a_ready as base

_TITLE_DASH_PATTERN = re.compile(r"\s*[-‐‑‒–—―−]\s*")
_ORIGINAL_VALIDATE = base.validate_ready_report


def _normalized_title(value: Any) -> str:
    normalized = _TITLE_DASH_PATTERN.sub(" - ", str(value or ""))
    return " ".join(normalized.split()).casefold()


def validate_ready_report(
    report: Mapping[str, Any],
    target: Mapping[str, Any],
):
    """Treat typography-only dash differences as the same frozen job title."""

    items = [item for item in report.get("reports") or [] if isinstance(item, Mapping)]
    inspections = [item for item in items if item.get("mode") == "inspect"]
    official_title = ""
    if len(inspections) == 1:
        posting = inspections[0].get("posting_metadata") or {}
        if isinstance(posting, Mapping):
            official_title = str(posting.get("title") or "")

    compatible_target = target
    frozen_role = str(target.get("role") or "")
    if (
        official_title
        and _normalized_title(official_title) == _normalized_title(frozen_role)
        and official_title != frozen_role
    ):
        compatible_target = dict(target)
        compatible_target["role"] = official_title

    return _ORIGINAL_VALIDATE(report, compatible_target)


base.validate_ready_report = validate_ready_report


if __name__ == "__main__":
    base.main()
