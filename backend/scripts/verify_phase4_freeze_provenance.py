#!/usr/bin/env python3
"""Verify Day 28 Phase 4 frozen source/fixture digests against Git history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.phase4_candidate_gate import FREEZE_PATH
from app.services.phase4_freeze_provenance import verify_freeze_source_provenance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Repository root containing .git.",
    )
    parser.add_argument(
        "--freeze",
        default=FREEZE_PATH,
        help="Freeze JSON path relative to the repository root.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    freeze_path = root / args.freeze
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    report = verify_freeze_source_provenance(root=root, freeze=freeze)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("verified") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
