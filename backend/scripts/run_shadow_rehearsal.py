#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.shadow_rehearsal import run_shadow_rehearsal


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a measured no-submit JobTomatik shadow rehearsal")
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = run_shadow_rehearsal(
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
