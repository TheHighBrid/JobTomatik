#!/usr/bin/env python3
"""Validate a manifest-driven Greenhouse pilot batch without hiding CI defects.

Pilot batch branches intentionally exercise several public job URLs at once. A stale
posting or a form that reaches a known manual-review boundary is useful evidence and
must not fail the entire batch. Unexpected exceptions, malformed reports, or any final
submit action still fail closed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable

SAFE_NONQUALIFYING_ERRORS = (
    "Greenhouse surface was detected but was not certification-ready.",
    "The supplied URL was not detected as a Greenhouse application.",
    "Required application fields need review before the ATS flow can continue.",
    "A CAPTCHA or human-verification challenge requires manual completion.",
)


def _is_stale_greenhouse_404(error: str) -> bool:
    return (
        "HTTPStatusError" in error
        and "404 Not Found" in error
        and "boards-api.greenhouse.io" in error
    )


def _iter_reports(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    reports = payload.get("reports")
    if not isinstance(reports, list) or not reports:
        raise ValueError("Greenhouse pilot report does not contain any target reports")
    for index, item in enumerate(reports):
        if not isinstance(item, dict):
            raise ValueError(f"Greenhouse pilot target report {index} is not an object")
        yield item


def evaluate_batch_report(payload: Dict[str, Any]) -> Dict[str, int]:
    if payload.get("final_submit_clicked") is not False:
        raise ValueError("Greenhouse pilot batch did not explicitly preserve final_submit_clicked=false")

    qualifying = 0
    nonqualifying = 0

    for index, item in enumerate(_iter_reports(payload)):
        if item.get("final_submit_clicked") is not False:
            raise ValueError(
                f"Greenhouse pilot target {index} did not explicitly preserve final_submit_clicked=false"
            )

        if item.get("passed") is True:
            qualifying += 1
            continue

        error = str(item.get("error") or "").strip()
        if _is_stale_greenhouse_404(error) or any(marker in error for marker in SAFE_NONQUALIFYING_ERRORS):
            nonqualifying += 1
            continue

        raise ValueError(
            f"Greenhouse pilot target {index} failed unexpectedly: {error or 'missing error detail'}"
        )

    return {
        "targets": qualifying + nonqualifying,
        "qualifying": qualifying,
        "nonqualifying": nonqualifying,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        default="greenhouse-live-certification.json",
        help="Path to the retained Greenhouse certification JSON report",
    )
    args = parser.parse_args()

    path = Path(args.report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = evaluate_batch_report(payload)
    print(
        "Greenhouse pilot batch retained "
        f"{summary['qualifying']} qualifying and {summary['nonqualifying']} safe non-qualifying "
        f"target(s) across {summary['targets']} total target(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
