#!/usr/bin/env python3
"""Native bridge for one-shot supervised Lever runtime-control requests."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.lever_pilot_control_request import (  # noqa: E402
    CONTROL_DIR,
    INFLIGHT_PATH,
    LeverPilotControlError,
    OWNER_PATH,
    REQUEST_PATH,
    STATUS_PATH,
    claim_control_request,
    complete_control_request,
    recover_inflight_without_replay,
)


def _runtime_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip().lower()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LeverPilotControlError(
            "LEVER_PILOT_CONTROL_RUNTIME_REVISION_UNAVAILABLE"
        ) from exc
    if not re.fullmatch(r"[0-9a-f]{7,64}", revision):
        raise LeverPilotControlError(
            "LEVER_PILOT_CONTROL_RUNTIME_REVISION_INVALID"
        )
    return revision


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claim and finalize signed JobTomatik native pilot-control requests."
    )
    parser.add_argument(
        "action",
        choices=("claim-request", "complete-request", "recover-inflight"),
    )
    parser.add_argument("--request-id")
    parser.add_argument("--outcome", choices=("success", "failed"))
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--control-dir", type=Path, default=CONTROL_DIR)
    args = parser.parse_args()

    request_path = args.control_dir / REQUEST_PATH.name
    inflight_path = args.control_dir / INFLIGHT_PATH.name
    status_path = args.control_dir / STATUS_PATH.name
    owner_path = args.control_dir / OWNER_PATH.name

    try:
        if args.action == "claim-request":
            request = claim_control_request(
                runtime_revision=_runtime_revision(),
                request_path=request_path,
                inflight_path=inflight_path,
                status_path=status_path,
            )
            if not request:
                return 3
            print(
                "\t".join(
                    (
                        str(request.get("request_id") or ""),
                        str(request.get("action") or ""),
                        str(request.get("application_id") or 0),
                    )
                )
            )
            return 0

        if args.action == "recover-inflight":
            result = recover_inflight_without_replay(
                inflight_path=inflight_path,
                status_path=status_path,
            )
            return 0 if result is not None else 3

        if not args.request_id:
            raise LeverPilotControlError("LEVER_PILOT_CONTROL_REQUEST_ID_REQUIRED")
        if not args.outcome:
            raise LeverPilotControlError("LEVER_PILOT_CONTROL_OUTCOME_REQUIRED")
        complete_control_request(
            request_id=args.request_id,
            outcome=args.outcome,
            exit_code=args.exit_code,
            inflight_path=inflight_path,
            status_path=status_path,
            owner_path=owner_path,
        )
        return 0
    except LeverPilotControlError as exc:
        print(f"LEVER_PILOT_CONTROL_BRIDGE_FAILED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
