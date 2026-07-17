"""Environment-backed settings for bounded scheduled automation.

Kept separate from the core application settings so the operations layer can be deployed or
rolled back independently. All unattended behavior defaults to disabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class OperationsSettings:
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
    return OperationsSettings(
        autopilot_enabled=_env_bool("AUTOPILOT_ENABLED", False),
        default_daily_cap=_env_int("AUTOPILOT_DEFAULT_DAILY_CAP", 5, 1),
        default_weekly_cap=_env_int("AUTOPILOT_DEFAULT_WEEKLY_CAP", 20, 1),
        quiet_hours_start_utc=min(23, _env_int("AUTOPILOT_QUIET_HOURS_START_UTC", 0)),
        quiet_hours_end_utc=min(23, _env_int("AUTOPILOT_QUIET_HOURS_END_UTC", 6)),
        failure_threshold=_env_int("AUTOPILOT_FAILURE_THRESHOLD", 3, 1),
        failure_window_minutes=_env_int("AUTOPILOT_FAILURE_WINDOW_MINUTES", 60, 1),
        circuit_breaker_minutes=_env_int("AUTOPILOT_CIRCUIT_BREAKER_MINUTES", 120, 1),
        stale_attempt_minutes=_env_int("AUTOPILOT_STALE_ATTEMPT_MINUTES", 30, 5),
        disabled_platforms=os.getenv("AUTOPILOT_DISABLED_PLATFORMS", ""),
    )
