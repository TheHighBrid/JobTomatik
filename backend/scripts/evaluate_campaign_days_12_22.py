#!/usr/bin/env python3
"""Generate the truthful Days 12--22 campaign checkpoint report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.campaign_day_gates import build_day_12_22_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lever", default="evidence/lever-pilot-readiness.json")
    parser.add_argument(
        "--greenhouse", default="evidence/greenhouse-phase-a-readiness.json"
    )
    parser.add_argument(
        "--reported-progress",
        default="evidence/lever-days-12-22-owner-report.json",
    )
    parser.add_argument("--output", default="evidence/campaign-days-12-22.json")
    args = parser.parse_args()
    lever = json.loads(Path(args.lever).read_text(encoding="utf-8"))
    greenhouse = json.loads(Path(args.greenhouse).read_text(encoding="utf-8"))
    progress_path = Path(args.reported_progress)
    reported_progress = (
        json.loads(progress_path.read_text(encoding="utf-8"))
        if progress_path.is_file()
        else {}
    )
    report = build_day_12_22_report(lever, greenhouse, reported_progress)
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    # Blocked evidence/user gates are report outcomes, not tool failures.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
