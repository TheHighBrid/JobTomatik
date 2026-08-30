#!/usr/bin/env python3
"""Manage the two runtime switches required for the supervised Lever pilot.

This helper only edits the managed backend ``.env`` file. It never creates or
consumes a submission approval, queues work, opens a browser, or clicks submit.
The native Termux wrapper owns the restart/acceptance cycle around these changes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic_settings import PydanticBaseSettingsSource  # noqa: E402

from app.config import Settings  # noqa: E402


ENV_FILE = BACKEND_ROOT / ".env"
GLOBAL_SUBMIT_KEY = "ALLOW_REAL_APPLICATION_SUBMIT"
LEVER_PILOT_KEY = "LEVER_SUPERVISED_PILOT_ENABLED"


class _ManagedBackendSettings(Settings):
    """Read managed backend settings without caller-environment overrides."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[Settings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, dotenv_settings, file_secret_settings


def _settings(env_file: Path) -> Settings:
    return _ManagedBackendSettings(_env_file=env_file)


def _set_env_values(env_file: Path, updates: dict[str, str]) -> None:
    """Atomically replace exact keys while preserving unrelated operator config."""

    env_file.parent.mkdir(parents=True, exist_ok=True)
    original = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    mode = env_file.stat().st_mode & 0o777 if env_file.exists() else 0o600
    keys = set(updates)
    seen: set[str] = set()
    output: list[str] = []

    for raw_line in original.splitlines(keepends=True):
        stripped = raw_line.rstrip("\r\n")
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", stripped)
        key = match.group(1) if match else None
        if key not in keys:
            output.append(raw_line)
            continue
        if key in seen:
            # Collapse duplicate target keys so the resulting runtime value is
            # deterministic. Unrelated duplicate/operator lines remain untouched.
            continue
        ending = "\n" if raw_line.endswith("\n") else ""
        output.append(f"{key}={updates[key]}{ending}")
        seen.add(key)

    if output and not output[-1].endswith("\n"):
        output[-1] += "\n"
    for key in updates:
        if key not in seen:
            output.append(f"{key}={updates[key]}\n")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{env_file.name}.",
        suffix=".tmp",
        dir=str(env_file.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, env_file)
    finally:
        if temporary.exists():
            temporary.unlink()


def _status(settings: Settings) -> dict[str, Any]:
    armed = bool(
        settings.allow_real_application_submit
        and settings.lever_supervised_pilot_enabled
        and not settings.greenhouse_supervised_pilot_enabled
        and not settings.allow_real_followup_send
    )
    return {
        "mode": "lever_supervised" if armed else "safe_or_other",
        "lever_supervised_armed": armed,
        "allow_real_application_submit": bool(settings.allow_real_application_submit),
        "lever_supervised_pilot_enabled": bool(settings.lever_supervised_pilot_enabled),
        "greenhouse_supervised_pilot_enabled": bool(
            settings.greenhouse_supervised_pilot_enabled
        ),
        "allow_real_followup_send": bool(settings.allow_real_followup_send),
        "secret_key_safe_for_sensitive_runtime": not settings.uses_placeholder_secret,
        "one_time_application_approval_still_required": True,
        "submission_queued": False,
        "final_submit_clicked": False,
    }


def arm(env_file: Path = ENV_FILE) -> dict[str, Any]:
    """Arm only the global + Lever pilot switches, failing closed on conflicts."""

    before = _settings(env_file)
    if before.uses_placeholder_secret:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED SECRET_KEY must be non-placeholder and at least 32 UTF-8 bytes"
        )
    if before.allow_real_followup_send:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED real recruiter/follow-up sending must remain disabled"
        )
    if before.greenhouse_supervised_pilot_enabled:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED Greenhouse supervised pilot must be disabled"
        )

    _set_env_values(
        env_file,
        {
            GLOBAL_SUBMIT_KEY: "true",
            LEVER_PILOT_KEY: "true",
        },
    )
    try:
        after = _settings(env_file)
        status = _status(after)
        if not status["lever_supervised_armed"]:
            raise RuntimeError("managed settings did not resolve to Lever supervised mode")
        return status
    except Exception:
        # A failed arm must leave the persisted config fail-safe even if validation
        # uncovers a previously hidden runtime problem.
        _set_env_values(
            env_file,
            {
                GLOBAL_SUBMIT_KEY: "false",
                LEVER_PILOT_KEY: "false",
            },
        )
        raise


def disarm(env_file: Path = ENV_FILE) -> dict[str, Any]:
    """Persist the two consequential switches OFF before any restart is attempted."""

    _set_env_values(
        env_file,
        {
            GLOBAL_SUBMIT_KEY: "false",
            LEVER_PILOT_KEY: "false",
        },
    )
    settings = _settings(env_file)
    status = _status(settings)
    if settings.allow_real_application_submit or settings.lever_supervised_pilot_enabled:
        raise RuntimeError("LEVER_PILOT_DISARM_FAILED consequential switches remained enabled")
    return status


def verify_armed(env_file: Path = ENV_FILE) -> dict[str, Any]:
    settings = _settings(env_file)
    status = _status(settings)
    if not status["lever_supervised_armed"]:
        raise RuntimeError("LEVER_PILOT_NOT_ARMED")
    return status


def verify_disarmed(env_file: Path = ENV_FILE) -> dict[str, Any]:
    settings = _settings(env_file)
    status = _status(settings)
    if settings.allow_real_application_submit or settings.lever_supervised_pilot_enabled:
        raise RuntimeError("LEVER_PILOT_NOT_DISARMED")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage fail-safe Android Lever supervised-pilot runtime switches."
    )
    parser.add_argument(
        "action",
        choices=("arm", "disarm", "status", "verify-armed", "verify-disarmed"),
    )
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    args = parser.parse_args()

    try:
        if args.action == "arm":
            result = arm(args.env_file)
        elif args.action == "disarm":
            result = disarm(args.env_file)
        elif args.action == "verify-armed":
            result = verify_armed(args.env_file)
        elif args.action == "verify-disarmed":
            result = verify_disarmed(args.env_file)
        else:
            result = _status(_settings(args.env_file))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"LEVER_PILOT_RUNTIME_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
