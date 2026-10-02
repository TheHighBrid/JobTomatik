#!/usr/bin/env python3
"""Export the Day 28 Phase 4 candidate-selection and adapter-freeze gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.services.phase4_candidate_gate import build_phase4_candidate_gate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verification-commit",
        default=os.getenv("SOURCE_COMMIT") or os.getenv("GITHUB_SHA") or "",
        help="Exact 40-character source commit being verified.",
    )
    parser.add_argument(
        "--output",
        default="phase4-candidate-gate.json",
        help="JSON output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gate = build_phase4_candidate_gate(verification_commit=args.verification_commit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(gate, indent=2, sort_keys=True))
    return 0 if gate.get("gate_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
