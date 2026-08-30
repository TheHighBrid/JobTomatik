#!/usr/bin/env python3
"""Run the non-destructive Day 41 SQLite backup/restore drill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.day41_database_restore import run_sqlite_restore_drill


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, help="SQLite database file to open read-only")
    parser.add_argument(
        "--work-dir",
        default=".runtime/day41-restore-drill",
        help="Directory for temporary snapshot/restored database files",
    )
    parser.add_argument(
        "--output",
        default="evidence/day41-database-restore-drill.json",
        help="JSON report path",
    )
    args = parser.parse_args()

    report = run_sqlite_restore_drill(args.database, output_directory=args.work_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "report_sha256": report.get("report_sha256"),
                "output": str(output),
                "source_database_modified_by_drill": report.get(
                    "source_database_modified_by_drill"
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
