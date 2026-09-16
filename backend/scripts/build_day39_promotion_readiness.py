#!/usr/bin/env python3
"""Build a read-only Day 39 promotion-readiness report from retained JSON inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.day39_promotion_readiness import build_day39_promotion_readiness


def _load(path: str | None) -> dict:
    if not path:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day38-report", required=True)
    parser.add_argument("--day38-review", required=True)
    parser.add_argument("--release-matrix", required=True)
    parser.add_argument("--adapter-state", required=True)
    parser.add_argument("--runtime-safety", required=True)
    parser.add_argument("--owner-approval")
    parser.add_argument(
        "--output",
        default="evidence/day39-promotion-readiness.json",
    )
    args = parser.parse_args()

    report = build_day39_promotion_readiness(
        day38_report=_load(args.day38_report),
        day38_review=_load(args.day38_review),
        release_matrix=_load(args.release_matrix),
        adapter_state=_load(args.adapter_state),
        runtime_safety=_load(args.runtime_safety),
        owner_approval=_load(args.owner_approval),
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "technical_ready": report["technical_ready"],
                "owner_approval_required": report["owner_approval_required"],
                "passed": report["passed"],
                "promotion_authorized": report["promotion_authorized"],
                "live_window_authorized": report["live_window_authorized"],
                "release_candidate_revision": report["release_candidate_revision"],
                "report_sha256": report["report_sha256"],
                "next_action": report["next_action"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )

    if report["passed"]:
        return 0
    if report["technical_ready"] and report["owner_approval_required"]:
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
