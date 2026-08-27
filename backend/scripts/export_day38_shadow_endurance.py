#!/usr/bin/env python3
"""Export a retained Day 38 twenty-four-hour endurance report.

This command is post-run only. It never starts, advances, repairs, finalizes, or reviews
shadow evidence. A non-passing session exits nonzero.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.services.certification_scale import current_revision
from app.services.day38_shadow_endurance import build_day38_shadow_endurance_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--verification-revision", default=None)
    parser.add_argument(
        "--output",
        default="evidence/day38-twenty-four-hour-shadow-endurance.json",
    )
    args = parser.parse_args()

    revision = str(args.verification_revision or current_revision())
    db = SessionLocal()
    try:
        report = build_day38_shadow_endurance_report(
            db,
            session_id=args.session_id,
            user_id=args.user_id,
            expected_revision=revision,
        )
    finally:
        db.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "session_id": report["session_id"],
                "passed": report["passed"],
                "day39_entry_eligible": report["day39_entry_eligible"],
                "candidate_revision": report["candidate_revision"],
                "persisted_elapsed_seconds": report["persisted_elapsed_seconds"],
                "policy_transition_checks": report[
                    "production_policy_transitions"
                ]["checks"],
                "report_sha256": report["report_sha256"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
