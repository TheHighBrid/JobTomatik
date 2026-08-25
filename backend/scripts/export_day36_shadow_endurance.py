#!/usr/bin/env python3
"""Export a retained Day 36 four-hour endurance report from the runtime database.

This command is intentionally post-run only. It does not create, advance, finalize, or
repair a shadow session. A non-passing session exits nonzero so a short or incomplete
campaign cannot be mistaken for Day 36 evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Support the documented direct CLI invocation from a repository checkout. When Python
# executes ``scripts/export_day36_shadow_endurance.py`` directly, it places ``scripts``
# rather than the backend root on sys.path, so ``app`` would otherwise be unresolved.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.services.certification_scale import current_revision
from app.services.day36_shadow_endurance import build_day36_shadow_endurance_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--verification-revision", default=None)
    parser.add_argument(
        "--output",
        default="evidence/day36-four-hour-shadow-endurance.json",
    )
    args = parser.parse_args()

    revision = str(args.verification_revision or current_revision())
    db = SessionLocal()
    try:
        report = build_day36_shadow_endurance_report(
            db,
            session_id=args.session_id,
            user_id=args.user_id,
            expected_revision=revision,
        )
    finally:
        db.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "session_id": report["session_id"],
        "passed": report["passed"],
        "day37_entry_eligible": report["day37_entry_eligible"],
        "candidate_revision": report["candidate_revision"],
        "persisted_elapsed_seconds": report["persisted_elapsed_seconds"],
        "report_sha256": report["report_sha256"],
        "output": str(output),
    }, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
