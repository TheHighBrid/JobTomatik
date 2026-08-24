"""Fail-closed operator controls for Day 34 autonomy operations.

The control state is account-scoped and persisted inside ``User.automation_settings``.
It never grants submission authority. ``paused`` blocks both new scheduler admission and
pre-browser worker execution. ``draining`` blocks new scheduler admission while allowing
already-created work to finish through the normal policy/safety gates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


AUTONOMY_CONTROL_KEY = "day34_autonomy_control"
AUTONOMY_CONTROL_VERSION = "android-autonomy-control-v1"
MODE_RUNNING = "running"
MODE_PAUSED = "paused"
MODE_DRAINING = "draining"
VALID_MODES = frozenset({MODE_RUNNING, MODE_PAUSED, MODE_DRAINING})
MAX_CONTROL_HISTORY = 20
_MISSING_SETTINGS = object()


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def autonomy_control_state(user) -> dict[str, Any]:
    raw_settings = getattr(user, "automation_settings", _MISSING_SETTINGS)
    principal_valid = raw_settings is not _MISSING_SETTINGS
    if principal_valid:
        try:
            settings = dict(raw_settings or {})
        except (TypeError, ValueError):
            settings = {}
            principal_valid = False
    else:
        settings = {}

    raw = settings.get(AUTONOMY_CONTROL_KEY)
    value = dict(raw) if isinstance(raw, dict) else {}
    requested_mode = str(value.get("mode") or MODE_RUNNING).strip().lower()
    mode_valid = requested_mode in VALID_MODES
    valid = principal_valid and mode_valid
    mode = requested_mode if valid else MODE_PAUSED
    return {
        "version": AUTONOMY_CONTROL_VERSION,
        "mode": mode,
        "valid": valid,
        "updated_at": value.get("updated_at"),
        "updated_by_user_id": value.get("updated_by_user_id"),
        "reason": value.get("reason"),
        "history": list(value.get("history") or [])[-MAX_CONTROL_HISTORY:],
        "scheduler_admission_allowed": valid and mode == MODE_RUNNING,
        "prebrowser_worker_allowed": valid and mode in {MODE_RUNNING, MODE_DRAINING},
        "submission_authorized": False,
    }


def set_autonomy_control_mode(
    user,
    *,
    mode: str,
    actor_user_id: int,
    reason: str | None = None,
) -> dict[str, Any]:
    normalized = str(mode or "").strip().lower()
    if normalized not in VALID_MODES:
        raise ValueError(f"Unsupported autonomy control mode: {mode}")

    previous = autonomy_control_state(user)
    now = _iso_now()
    history = list(previous.get("history") or [])[-(MAX_CONTROL_HISTORY - 1):]
    history.append(
        {
            "from_mode": previous.get("mode"),
            "to_mode": normalized,
            "at": now,
            "actor_user_id": int(actor_user_id),
            "reason": (reason or "").strip()[:300] or None,
        }
    )
    settings = dict(user.automation_settings or {})
    settings[AUTONOMY_CONTROL_KEY] = {
        "version": AUTONOMY_CONTROL_VERSION,
        "mode": normalized,
        "updated_at": now,
        "updated_by_user_id": int(actor_user_id),
        "reason": (reason or "").strip()[:300] or None,
        "history": history,
    }
    user.automation_settings = settings
    return autonomy_control_state(user)


def scheduler_control_decision(user) -> dict[str, Any]:
    control = autonomy_control_state(user)
    if control["scheduler_admission_allowed"]:
        return {
            "allowed": True,
            "code": "operator_control_running",
            "reason": "Operator control allows new scheduler admission.",
            "mode": control["mode"],
        }
    code = "operator_control_invalid" if not control["valid"] else f"operator_{control['mode']}"
    reason = (
        "Operator control state is invalid and therefore fails closed."
        if not control["valid"]
        else (
            "Operator pause is active; no new scheduled work may be admitted."
            if control["mode"] == MODE_PAUSED
            else "Queue drain is active; no new scheduled work may be admitted."
        )
    )
    return {"allowed": False, "code": code, "reason": reason, "mode": control["mode"]}


def worker_control_decision(user) -> dict[str, Any]:
    control = autonomy_control_state(user)
    if control["prebrowser_worker_allowed"]:
        return {
            "allowed": True,
            "code": (
                "operator_drain_allows_existing_work"
                if control["mode"] == MODE_DRAINING
                else "operator_control_running"
            ),
            "reason": (
                "Queue drain permits already-created work to finish through normal safety gates."
                if control["mode"] == MODE_DRAINING
                else "Operator control allows pre-browser worker execution."
            ),
            "mode": control["mode"],
        }
    code = "operator_control_invalid" if not control["valid"] else "operator_paused"
    reason = (
        "Operator control state is invalid and therefore fails closed before browser execution."
        if not control["valid"]
        else "Operator pause is active; browser execution is blocked pending review."
    )
    return {"allowed": False, "code": code, "reason": reason, "mode": control["mode"]}


__all__ = [
    "AUTONOMY_CONTROL_KEY",
    "AUTONOMY_CONTROL_VERSION",
    "MODE_DRAINING",
    "MODE_PAUSED",
    "MODE_RUNNING",
    "VALID_MODES",
    "autonomy_control_state",
    "scheduler_control_decision",
    "set_autonomy_control_mode",
    "worker_control_decision",
]
