#!/usr/bin/env python3
"""JobTomatik operator CLI.

`jobtomatik greenhouse preflight <application>` is read-only. It does not submit,
issue an approval, or change application state.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.services.greenhouse_oh1_preflight import (  # noqa: E402
    render_preflight_report,
    report_json,
    run_gh_oh1_preflight,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobtomatik")
    sub = parser.add_subparsers(dest="command", required=True)
    greenhouse = sub.add_parser("greenhouse")
    greenhouse_sub = greenhouse.add_subparsers(dest="greenhouse_command", required=True)
    preflight = greenhouse_sub.add_parser("preflight")
    preflight.add_argument("application", type=int, help="Application id to inspect")
    preflight.add_argument("--json", action="store_true", help="Emit the machine-readable report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "greenhouse" or args.greenhouse_command != "preflight":
        parser.error("only greenhouse preflight is available")
    db = SessionLocal()
    try:
        report = run_gh_oh1_preflight(db, args.application)
    finally:
        db.close()
    if args.json:
        sys.stdout.write(report_json(report))
    else:
        sys.stdout.write(render_preflight_report(report))
    if report.get("submit_attempted") is True:
        return 3
    return 0 if report.get("ready") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
