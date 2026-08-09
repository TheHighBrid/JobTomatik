"""Environment-backed settings for bounded scheduled automation.

Kept separate from the core application settings so the operations layer can be deployed or
rolled back independently. All unattended behavior defaults to disabled.

Process environment variables remain authoritative. For local/Android launches, values that
are not present in the process environment fall back to the same backend ``.env`` file used
by Pydantic settings. This keeps scheduler policy, shadow workers, API preflight, and launch
attestation on one configuration source without shell-sourcing a secrets file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPERATIONS_ENV_FILE = BACKEND_ROOT / ".env"
OPERATIONS_ENV_FILE_OVERRIDE = "JOBTOMATIK_OPERATIONS_ENV_FILE"


def _operations_env_values() -> dict[str, str]:
    configured = str(os.getenv(OPERATIONS_ENV_FILE_OVERRIDE) or "").strip()
    env_file = Path(configured).expanduser() if configured else DEFAULT_OPERATIONS_ENV_FILE
    if not env_file.is_file():
        return {}
    try:
        values = dotenv_values(env_file)
    except OSError:
        return {}
    return {
        str(key): str(value)
        for key, value in values.items()
        if key and value is not None
    }


def _raw_value(name: str, env_file_values: dict[str, str]) -> str | None:
    # An explicitly exported empty value is still authoritative and must not fall
    # through to a stale value in .env.
    if name in os.environ:
        return os.environ.get(name)
    return env_file_values.get(name)


def _env_bool(name: str, default: bool, env_file_values: dict[str, str]) -> bool:
    raw = _raw_value(name, env_file_values)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(
    name: str,
    default: int,
    env_file_values: dict[str, str],
    minimum: int = 0,
) -> int:
    raw = _raw_value(name, env_file_values)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class OperationsSettings:
    global_kill_switch: bool
    autopilot_enabled: bool
    default_daily_cap: int
    default_weekly_cap: int
    quiet_hours_start_utc: int
    quiet_hours_end_utc: int
    failure_threshold: int
    failure_window_minutes: int
    circuit_breaker_minutes: int
    stale_attempt_minutes: int
    disabled_platforms: str


@lru_cache
def get_operations_settings() -> OperationsSettings:
    env_file_values = _operations_env_values()
    return OperationsSettings(
        # False means normal bounded operation. True is the emergency stop and blocks
        # scheduled, live-submit, and retained-handoff execution before browser work.
        global_kill_switch=_env_bool(
            "AUTOMATION_GLOBAL_KILL_SWITCH", False, env_file_values
        ),
        autopilot_enabled=_env_bool("AUTOPILOT_ENABLED", False, env_file_values),
        default_daily_cap=_env_int(
            "AUTOPILOT_DEFAULT_DAILY_CAP", 5, env_file_values, 1
        ),
        default_weekly_cap=_env_int(
            "AUTOPILOT_DEFAULT_WEEKLY_CAP", 20, env_file_values, 1
        ),
        quiet_hours_start_utc=min(
            23,
            _env_int("AUTOPILOT_QUIET_HOURS_START_UTC", 0, env_file_values),
        ),
        quiet_hours_end_utc=min(
            23,
            _env_int("AUTOPILOT_QUIET_HOURS_END_UTC", 6, env_file_values),
        ),
        failure_threshold=_env_int(
            "AUTOPILOT_FAILURE_THRESHOLD", 3, env_file_values, 1
        ),
        failure_window_minutes=_env_int(
            "AUTOPILOT_FAILURE_WINDOW_MINUTES", 60, env_file_values, 1
        ),
        circuit_breaker_minutes=_env_int(
            "AUTOPILOT_CIRCUIT_BREAKER_MINUTES", 120, env_file_values, 1
        ),
        stale_attempt_minutes=_env_int(
            "AUTOPILOT_STALE_ATTEMPT_MINUTES", 30, env_file_values, 5
        ),
        disabled_platforms=str(
            _raw_value("AUTOPILOT_DISABLED_PLATFORMS", env_file_values) or ""
        ),
    )
