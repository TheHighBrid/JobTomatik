#!/usr/bin/env python3
"""Validate exact runtime identity before sensitive JobTomatik processes start."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.services.operations_settings import get_operations_settings  # noqa: E402
from app.services.runtime_identity import runtime_identity_manifest  # noqa: E402


def sensitive_runtime_requested() -> bool:
    core = get_settings()
    operations = get_operations_settings()
    return any(
        (
            core.is_production,
            operations.autopilot_enabled,
            core.allow_real_application_submit,
            core.allow_real_followup_send,
            core.greenhouse_supervised_pilot_enabled,
            core.lever_supervised_pilot_enabled,
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
    configuration_error: str | None = None
    try:
        sensitive = sensitive_runtime_requested()
    except Exception as exc:  # Fail closed without exposing config/secrets in output.
        sensitive = True
        configuration_error = exc.__class__.__name__

    require = args.require_attested or (args.require_sensitive and sensitive)
    result = {
        **identity,
        "sensitive_runtime_requested": sensitive,
        "attestation_required": require,
        "configuration_valid": configuration_error is None,
    }
    if configuration_error is not None:
        result["configuration_error"] = configuration_error
    print(json.dumps(result, sort_keys=True))

    if configuration_error is not None:
        print(
            "JobTomatik runtime configuration validation failed before process startup.",
            file=sys.stderr,
        )
        return 2

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
