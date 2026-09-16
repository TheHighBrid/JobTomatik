#!/usr/bin/env python3
"""Build the separate signed Day 39 Lever autonomy-release record from retained evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.services.day39_lever_promotion import build_day39_lever_promotion
from app.services.operations_policy import operations_readiness_manifest


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the signed Lever autonomy release only when genuine Phase B, "
            "Day 35 recovery/policy, Day 36-38 shadow, exact-head promotion, and "
            "owner approval evidence all pass."
        )
    )
    parser.add_argument("--promotion-readiness", required=True)
    parser.add_argument("--lever-readiness", required=True)
    parser.add_argument("--phase4-freeze", required=True)
    parser.add_argument("--day35-gate", required=True)
    parser.add_argument("--day36-report", required=True)
    parser.add_argument("--day37-report", required=True)
    parser.add_argument("--day38-report", required=True)
    parser.add_argument("--owner-approval", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument(
        "--output",
        default="evidence/lever-autonomy-release.json",
    )
    args = parser.parse_args()

    signing_key = os.getenv("AUTONOMY_CERTIFICATION_SIGNING_KEY", "")
    result = build_day39_lever_promotion(
        promotion_readiness=_load(args.promotion_readiness),
        lever_readiness=_load(args.lever_readiness),
        phase4_freeze=_load(args.phase4_freeze),
        day35_gate=_load(args.day35_gate),
        day36_report=_load(args.day36_report),
        day37_report=_load(args.day37_report),
        day38_report=_load(args.day38_report),
        operations_readiness=operations_readiness_manifest(),
        owner_approval=_load(args.owner_approval),
        signing_key=signing_key,
        key_id=args.key_id,
    )
    _write(args.output, result)
    print(
        json.dumps(
            {
                "output": args.output,
                "promotion_record_generated": result.get("promotion_record_generated") is True,
                "release_candidate_revision": result.get("release_candidate_revision"),
                "blockers": result.get("blockers") or [],
                "report_sha256": result.get("report_sha256"),
                "real_submission_enabled": False,
                "live_window_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0 if result.get("promotion_record_generated") is True else 3


if __name__ == "__main__":
    raise SystemExit(main())
