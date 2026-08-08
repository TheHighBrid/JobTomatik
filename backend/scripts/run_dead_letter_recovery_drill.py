#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import models as _models  # noqa: F401,E402
from app.services.dead_letter_drill import run_dead_letter_recovery_drill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated dead-letter recovery drill")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = run_dead_letter_recovery_drill(output_path=args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
