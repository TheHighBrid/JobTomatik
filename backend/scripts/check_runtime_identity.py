#!/usr/bin/env python3
"""Validate exact runtime identity before sensitive JobTomatik processes start."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.runtime_identity import runtime_identity_manifest  # noqa: E402


def _truthy(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def sensitive_runtime_requested() -> bool:
    return any(
        (
            str(os.getenv("APP_ENV") or "development").strip().lower() == "production",
            _truthy("AUTOPILOT_ENABLED"),
            _truthy("ALLOW_REAL_APPLICATION_SUBMIT"),
            _truthy("ALLOW_REAL_FOLLOWUP_SEND"),
            _truthy("GREENHOUSE_SUPERVISED_PILOT_ENABLED"),
            _truthy("LEVER_SUPERVISED_PILOT_ENABLED"),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-sensitive",
        action="store_true",
        help="Require deployment attestation whenever a sensitive runtime mode is enabled.",
    )
    parser.add_argument(
        "--require-attested",
        action="store_true",
        help="Require deployment attestation unconditionally.",
    )
    args = parser.parse_args()

    identity = runtime_identity_manifest()
    sensitive = sensitive_runtime_requested()
    require = args.require_attested or (args.require_sensitive and sensitive)
    result = {
        **identity,
        "sensitive_runtime_requested": sensitive,
        "attestation_required": require,
    }
    print(json.dumps(result, sort_keys=True))

    if require and not identity["deployment_attested"]:
        print(
            "JobTomatik runtime identity attestation failed: set matching "
            "JOBTOMATIK_RUNTIME_REVISION and JOBTOMATIK_EXPECTED_REVISION values.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
