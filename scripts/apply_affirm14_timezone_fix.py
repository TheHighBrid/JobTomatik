#!/usr/bin/env python3
"""Apply Affirm #14 timezone fix to supervised_submission.py in-place.

Root cause: SubmissionApproval.expires_at is DateTime(timezone=True) while
_now() returned naive datetime.utcnow(), causing:
  TypeError: can't compare offset-naive and offset-aware datetimes

Usage (from repo root):
  python3 scripts/apply_affirm14_timezone_fix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path("backend/app/services/supervised_submission.py")

OLD_IMPORT = "from datetime import datetime, timedelta"
NEW_IMPORT = "from datetime import datetime, timedelta, timezone"

OLD_NOW = "def _now() -> datetime:\n    return datetime.utcnow()"
NEW_NOW = '''def _now() -> datetime:
    """Return timezone-aware UTC now.

    SubmissionApproval timestamp columns are DateTime(timezone=True).
    Naive utcnow() caused TypeError on Affirm #14.
    """
    return datetime.now(timezone.utc)'''


def main() -> int:
    if not TARGET.is_file():
        print(f"missing {TARGET}", file=sys.stderr)
        return 1
    text = TARGET.read_text()
    if "datetime.now(timezone.utc)" in text and "utcnow" not in text.split("def _now")[1].split("def ")[0]:
        print("already fixed")
        return 0
    if OLD_NOW not in text:
        print("expected _now() pattern not found", file=sys.stderr)
        return 1
    if OLD_IMPORT not in text:
        print("expected import not found", file=sys.stderr)
        return 1
    text = text.replace(OLD_IMPORT, NEW_IMPORT, 1).replace(OLD_NOW, NEW_NOW, 1)
    TARGET.write_text(text)
    print(f"applied timezone fix to {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
