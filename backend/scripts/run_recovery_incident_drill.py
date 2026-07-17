#!/usr/bin/env python3
"""Run the isolated JobTomatik recovery and incident-response drill."""

from __future__ import annotations

import argparse
import json
import sys

from app.services.recovery_drill import run_recovery_incident_drill


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated stale-attempt recovery incident drill."
    )
    parser.add_argument(
        "--output",
        default="recovery-incident-drill.json",
        help="JSON report path relative to the current working directory.",
    )
    args = parser.parse_args()

    report = run_recovery_incident_drill(output_path=args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
