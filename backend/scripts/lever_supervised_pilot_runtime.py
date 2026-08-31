#!/usr/bin/env python3
"""Validate and preserve fail-safe configuration for a supervised Lever window.

The live supervised window is carried by an owner-, token-, and revision-bound runtime
marker installed only for one managed restart. This helper never persists an enabled
submit switch. Its only configuration write forces consequential persisted switches
OFF.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from dotenv import dotenv_values

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic_settings import PydanticBaseSettingsSource  # noqa: E402

from app.config import Settings  # noqa: E402
from app.services.supervised_runtime_mode import (  # noqa: E402
    DEFAULT_MARKER_PATH,
    clear_owner_bound_marker,
    create_owner_bound_marker,
    lever_supervised_runtime_marker_active,
    load_marker,
)


ENV_FILE = BACKEND_ROOT / ".env"
GLOBAL_SUBMIT_KEY = "ALLOW_REAL_APPLICATION_SUBMIT"
LEVER_PILOT_KEY = "LEVER_SUPERVISED_PILOT_ENABLED"
AUTOPILOT_KEY = "AUTOPILOT_ENABLED"


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
        raise RuntimeError("LEVER_PILOT_RUNTIME_REVISION_UNAVAILABLE") from exc
    if not re.fullmatch(r"[0-9a-f]{7,64}", revision):
        raise RuntimeError("LEVER_PILOT_RUNTIME_REVISION_INVALID")
    return revision


def _env_values(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        return {}
    values = dotenv_values(env_file)
    return {
        str(key): str(value)
        for key, value in values.items()
        if key and value is not None
    }


def _env_bool(values: dict[str, str], key: str, default: bool = False) -> bool:
    raw = values.get(key)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


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
        directory_fd = os.open(str(env_file.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _persisted_status(env_file: Path) -> dict[str, Any]:
    values = _env_values(env_file)
    real_submit = _env_bool(values, GLOBAL_SUBMIT_KEY)
    lever_pilot = _env_bool(values, LEVER_PILOT_KEY)
    autopilot = _env_bool(values, AUTOPILOT_KEY)
    return {
        "persisted_fail_safe": not real_submit and not lever_pilot,
        "persisted_allow_real_application_submit": real_submit,
        "persisted_lever_supervised_pilot_enabled": lever_pilot,
        "persisted_autopilot_enabled": autopilot,
        "live_process_mode_observed": False,
        "live_submission_state_observed": False,
        "one_time_application_approval_still_required": True,
    }


def persist_safe(env_file: Path = ENV_FILE) -> dict[str, Any]:
    """Persist only OFF values and verify them without parsing unrelated settings."""

    _set_env_values(
        env_file,
        {
            GLOBAL_SUBMIT_KEY: "false",
            LEVER_PILOT_KEY: "false",
        },
    )
    status = _persisted_status(env_file)
    if not status["persisted_fail_safe"]:
        raise RuntimeError("LEVER_PILOT_SAFE_PERSIST_FAILED consequential switches remained enabled")
    return status


def preflight_arm(env_file: Path = ENV_FILE) -> dict[str, Any]:
    """Prove the persisted config can safely host an ephemeral supervised window."""

    persisted = _persisted_status(env_file)
    if not persisted["persisted_fail_safe"]:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED persisted real-submit and Lever-pilot switches must be OFF"
        )
    if persisted["persisted_autopilot_enabled"]:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED AUTOPILOT_ENABLED must be false for a supervised window"
        )

    settings = _settings(env_file)
    if settings.uses_placeholder_secret:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED SECRET_KEY must be non-placeholder and at least 32 UTF-8 bytes"
        )
    if settings.allow_real_followup_send:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED real recruiter/follow-up sending must remain disabled"
        )
    if settings.greenhouse_supervised_pilot_enabled:
        raise RuntimeError(
            "LEVER_PILOT_ARM_BLOCKED Greenhouse supervised pilot must be disabled"
        )

    return {
        **persisted,
        "configuration_valid": True,
        "secret_key_safe_for_sensitive_runtime": True,
        "ephemeral_runtime_marker_required": True,
        "runtime_revision": _runtime_revision(),
    }


def create_marker(
    owner_pid: int,
    launch_token: str,
    marker_path: Path = DEFAULT_MARKER_PATH,
) -> dict[str, Any]:
    """Create the exact-restart marker immediately before managed restart."""

    revision = _runtime_revision()
    marker = create_owner_bound_marker(
        owner_pid,
        launch_token=launch_token,
        runtime_revision=revision,
        path=marker_path,
    )
    return {
        "marker_active": True,
        "marker_path": str(marker_path),
        "owner_pid": marker["owner_pid"],
        "owner_start_ticks": marker["owner_start_ticks"],
        "runtime_revision": marker["runtime_revision"],
        "submission_approval_granted": False,
    }


def clear_marker(marker_path: Path = DEFAULT_MARKER_PATH) -> dict[str, Any]:
    """Remove the capability marker before an ordinary fail-safe restart."""

    clear_owner_bound_marker(marker_path)
    return {
        "marker_active": False,
        "marker_path": str(marker_path),
        "marker_present": marker_path.exists(),
    }


def verify_marker(
    launch_token: str,
    marker_path: Path = DEFAULT_MARKER_PATH,
) -> dict[str, Any]:
    """Fail closed unless owner, token, and checkout revision still match."""

    revision = _runtime_revision()
    active = lever_supervised_runtime_marker_active(
        marker_path,
        expected_launch_token=launch_token,
        expected_revision=revision,
    )
    marker = load_marker(marker_path)
    if not active:
        raise RuntimeError("LEVER_PILOT_RUNTIME_MARKER_INACTIVE")
    return {
        "marker_active": True,
        "marker_path": str(marker_path),
        "owner_pid": marker.get("owner_pid") if marker else None,
        "runtime_revision": revision,
        "submission_approval_granted": False,
    }


def status(env_file: Path = ENV_FILE) -> dict[str, Any]:
    """Report persisted configuration only, never infer queue or submit outcomes."""

    result = _persisted_status(env_file)
    try:
        settings = _settings(env_file)
    except Exception as exc:
        return {
            **result,
            "configuration_valid": False,
            "configuration_error": f"{type(exc).__name__}: {exc}",
            "secret_key_safe_for_sensitive_runtime": None,
        }
    return {
        **result,
        "configuration_valid": True,
        "configuration_error": None,
        "secret_key_safe_for_sensitive_runtime": not settings.uses_placeholder_secret,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate fail-safe Android Lever supervised-pilot configuration."
    )
    parser.add_argument(
        "action",
        choices=(
            "persist-safe",
            "preflight-arm",
            "create-marker",
            "clear-marker",
            "verify-marker",
            "status",
        ),
    )
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    parser.add_argument("--marker-path", type=Path, default=DEFAULT_MARKER_PATH)
    parser.add_argument("--owner-pid", type=int)
    parser.add_argument("--launch-token")
    args = parser.parse_args()

    try:
        if args.action == "persist-safe":
            result = persist_safe(args.env_file)
        elif args.action == "preflight-arm":
            result = preflight_arm(args.env_file)
        elif args.action == "create-marker":
            if args.owner_pid is None:
                raise RuntimeError("LEVER_PILOT_MARKER_OWNER_PID_REQUIRED")
            if not args.launch_token:
                raise RuntimeError("LEVER_PILOT_MARKER_LAUNCH_TOKEN_REQUIRED")
            result = create_marker(args.owner_pid, args.launch_token, args.marker_path)
        elif args.action == "clear-marker":
            result = clear_marker(args.marker_path)
        elif args.action == "verify-marker":
            if not args.launch_token:
                raise RuntimeError("LEVER_PILOT_MARKER_LAUNCH_TOKEN_REQUIRED")
            result = verify_marker(args.launch_token, args.marker_path)
        else:
            result = status(args.env_file)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"LEVER_PILOT_RUNTIME_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
