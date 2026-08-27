"""Runtime integration for the Day 38 twenty-four-hour shadow stage.

The integration keeps the real shadow scheduler on the explicit ``shadow_test`` policy
profile while retaining a diagnostic snapshot of what the production policy would have
decided at the same cycle timestamp. Diagnostic production decisions never authorize,
block, or mutate shadow execution.

It also replaces the intentional Android 24-hour hard lock with the fail-closed Day 38
admission contract once this module is installed by the API and managed worker.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any

from sqlalchemy import func

from app.models.application import Application
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.models.user import User
from app.services.certification_scale import ensure_aware
from app.services.day38_shadow_admission import (
    DAY38_RUNTIME_RECEIPT_MAX_AGE_SECONDS,
    DAY38_SECONDS,
    DAY38_TARGET,
    day38_android_launch_admission,
)
from app.services.operations_policy import evaluate_autopilot_policy, is_quiet_hour
from app.services.operations_settings import get_operations_settings


DAY38_POLICY_TELEMETRY_VERSION = "day38-production-policy-diagnostic-v1"
DAY38_POLICY_SNAPSHOT_KEY = "day38_production_policy_diagnostic"
_API_INSTALLED = False
_MODEL_INSTALLED = False
_WORKER_INSTALLED = False


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(1, int(default))
    return max(1, parsed)


def _naive_utc(value: datetime | None) -> datetime:
    aware = ensure_aware(value) or datetime.now(timezone.utc)
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def production_policy_diagnostic(
    db,
    user: User,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return non-authoritative production-policy state for one shadow-cycle timestamp."""

    current = _naive_utc(now)
    operations = get_operations_settings()
    user_settings = dict(user.automation_settings or {})

    requested_daily = _positive_int(
        user_settings.get("auto_apply_daily_limit"),
        operations.default_daily_cap,
    )
    requested_weekly = _positive_int(
        user_settings.get("auto_apply_weekly_limit"),
        operations.default_weekly_cap,
    )
    effective_daily = min(int(operations.default_daily_cap), requested_daily)
    effective_weekly = min(int(operations.default_weekly_cap), requested_weekly)

    rolling_24h_start = current - timedelta(days=1)
    rolling_7d_start = current - timedelta(days=7)
    daily_count = int(
        db.query(func.count(Application.id))
        .filter(
            Application.user_id == int(user.id),
            Application.created_at >= rolling_24h_start,
            Application.created_at <= current,
        )
        .scalar()
        or 0
    )
    weekly_count = int(
        db.query(func.count(Application.id))
        .filter(
            Application.user_id == int(user.id),
            Application.created_at >= rolling_7d_start,
            Application.created_at <= current,
        )
        .scalar()
        or 0
    )

    quiet_start = int(user_settings.get("quiet_hours_start_utc", operations.quiet_hours_start_utc))
    quiet_end = int(user_settings.get("quiet_hours_end_utc", operations.quiet_hours_end_utc))
    quiet_start = min(23, max(0, quiet_start))
    quiet_end = min(23, max(0, quiet_end))

    decision = evaluate_autopilot_policy(
        db,
        user,
        now=current,
        policy_profile="production",
    ).to_dict()

    return {
        "version": DAY38_POLICY_TELEMETRY_VERSION,
        "observed_at": current.replace(tzinfo=timezone.utc).isoformat(),
        "authoritative": False,
        "execution_policy_profile": "shadow_test",
        "diagnostic_policy_profile": "production",
        "production_decision": decision,
        "quiet_hours": {
            "start_hour_utc": quiet_start,
            "end_hour_utc": quiet_end,
            "configured": quiet_start != quiet_end,
            "active": is_quiet_hour(current, quiet_start, quiet_end),
        },
        "rolling_24h_capacity": {
            "window_start": rolling_24h_start.replace(tzinfo=timezone.utc).isoformat(),
            "count": daily_count,
            "cap": effective_daily,
            "remaining": max(0, effective_daily - daily_count),
            "at_or_above_cap": daily_count >= effective_daily,
        },
        "rolling_7d_capacity": {
            "window_start": rolling_7d_start.replace(tzinfo=timezone.utc).isoformat(),
            "count": weekly_count,
            "cap": effective_weekly,
            "remaining": max(0, effective_weekly - weekly_count),
            "at_or_above_cap": weekly_count >= effective_weekly,
        },
        "safety": {
            "used_to_authorize_shadow_execution": False,
            "used_to_block_shadow_execution": False,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    }


def _install_api_preflight() -> None:
    global _API_INSTALLED
    if _API_INSTALLED:
        return

    from app.api import shadow_runs
    from app.services.full_stack_shadow import full_stack_shadow_preflight

    original = shadow_runs._shadow_start_preflight
    if getattr(original, "_day38_preflight_wrapper", False):
        _API_INSTALLED = True
        return

    @wraps(original)
    def wrapped(db, user: User, *, target_evidence_type: str):
        if (
            os.environ.get("JOBTOMATIK_RUNTIME_MODE") != "android_managed"
            or str(target_evidence_type or "") != DAY38_TARGET
        ):
            return original(db, user, target_evidence_type=target_evidence_type)

        payload = full_stack_shadow_preflight(
            db,
            user,
            target_evidence_type=target_evidence_type,
        )
        admission = day38_android_launch_admission(
            db,
            user,
            candidate_revision=str(payload.get("candidate_revision") or ""),
            requested_duration_seconds=int(payload.get("requested_duration_seconds") or 0),
        )
        checks = payload.setdefault("checks", {})
        blockers = list(payload.get("blockers") or [])
        for name, passed in dict(admission.get("checks") or {}).items():
            check_name = f"day38_{name}"
            checks[check_name] = bool(passed)
            if not passed and check_name not in blockers:
                blockers.append(check_name)
        for blocker in admission.get("blockers") or []:
            normalized = f"day38:{blocker}"
            if normalized not in blockers:
                blockers.append(normalized)

        payload["day38_admission"] = admission
        payload["stage_gate"] = {
            "stage": "day38",
            "target_evidence_type": DAY38_TARGET,
            "ok": admission.get("ok") is True and not blockers,
            "blockers": list(blockers),
            "submission_authorized": False,
            "outreach_authorized": False,
        }
        payload["blockers"] = blockers
        payload["ok"] = not blockers
        if blockers:
            payload["expected_start_acknowledgment"] = None
        return payload

    wrapped._day38_preflight_wrapper = True
    wrapped._day38_preflight_original = original
    shadow_runs._shadow_start_preflight = wrapped
    _API_INSTALLED = True


def _install_model_guards() -> None:
    global _MODEL_INSTALLED
    if _MODEL_INSTALLED:
        return

    from app.models import certification
    from app.services.runtime_acceptance import runtime_acceptance_status

    original_admission = certification._require_android_shadow_admission
    original_live = certification._require_android_shadow_live_launch_policy
    if getattr(original_admission, "_day38_model_wrapper", False):
        _MODEL_INSTALLED = True
        return

    @wraps(original_admission)
    def admission_guard(target: ShadowRunSession) -> None:
        if (
            os.environ.get("JOBTOMATIK_RUNTIME_MODE") != "android_managed"
            or str(target.target_evidence_type or "") != DAY38_TARGET
        ):
            return original_admission(target)

        receipt = runtime_acceptance_status(
            max_age_seconds=DAY38_RUNTIME_RECEIPT_MAX_AGE_SECONDS
        )
        if receipt.get("ok") is not True:
            blockers = ",".join(receipt.get("blockers") or []) or "runtime_acceptance_invalid"
            raise ValueError(
                "Android shadow_run_24h requires fresh exact-runtime acceptance: " + blockers
            )
        if str(receipt.get("revision") or "") != str(target.candidate_revision or ""):
            raise ValueError(
                "Android shadow_run_24h runtime revision does not match the campaign revision"
            )

    @wraps(original_live)
    def live_guard(session, target: ShadowRunSession) -> None:
        if (
            os.environ.get("JOBTOMATIK_RUNTIME_MODE") != "android_managed"
            or str(target.target_evidence_type or "") != DAY38_TARGET
        ):
            return original_live(session, target)

        blockers: list[str] = []
        if int(target.requested_duration_seconds or 0) != DAY38_SECONDS:
            blockers.append("requested_duration_not_exactly_24h")
        if target.final_submit_allowed is not False:
            blockers.append("final_submit_allowed_not_false")
        if target.stop_requested not in {False, None}:
            blockers.append("stop_requested_at_launch")

        with session.no_autoflush:
            user = (
                session.query(User)
                .filter(User.id == int(target.user_id), User.is_active == True)
                .first()
            )
            if user is None:
                blockers.append("active_user_missing")
            else:
                admission = day38_android_launch_admission(
                    session,
                    user,
                    candidate_revision=str(target.candidate_revision or ""),
                    requested_duration_seconds=int(target.requested_duration_seconds or 0),
                )
                blockers.extend(str(item) for item in (admission.get("blockers") or []))

        if blockers:
            raise ValueError(
                "Android shadow_run_24h live launch policy blocked: "
                + ",".join(sorted(set(blockers)))
            )

    admission_guard._day38_model_wrapper = True
    admission_guard._day38_model_original = original_admission
    live_guard._day38_model_wrapper = True
    live_guard._day38_model_original = original_live
    certification._require_android_shadow_admission = admission_guard
    certification._require_android_shadow_live_launch_policy = live_guard
    _MODEL_INSTALLED = True


def _install_worker_cycle_telemetry() -> None:
    global _WORKER_INSTALLED
    if _WORKER_INSTALLED:
        return

    from app.services import full_stack_shadow

    original = full_stack_shadow.execute_shadow_cycle
    if getattr(original, "_day38_cycle_wrapper", False):
        _WORKER_INSTALLED = True
        return

    @wraps(original)
    def wrapped(db, *, session_id: int, scheduler_runner=None, now: datetime | None = None):
        diagnostic: dict[str, Any] | None = None
        target_cycle_number: int | None = None
        session = (
            db.query(ShadowRunSession)
            .filter(ShadowRunSession.id == int(session_id))
            .first()
        )
        if (
            session is not None
            and str(session.target_evidence_type or "") == DAY38_TARGET
            and str(session.status or "") in full_stack_shadow.ACTIVE_SESSION_STATES
        ):
            expected_end = ensure_aware(session.expected_end_at)
            current = ensure_aware(now) or datetime.now(timezone.utc)
            if expected_end is None or current < expected_end:
                user = (
                    db.query(User)
                    .filter(User.id == int(session.user_id), User.is_active == True)
                    .first()
                )
                if user is not None:
                    diagnostic = production_policy_diagnostic(db, user, now=current)
                    target_cycle_number = (
                        int(session.cycles_completed or 0)
                        + int(session.cycles_failed or 0)
                        + 1
                    )

        result = original(
            db,
            session_id=int(session_id),
            scheduler_runner=scheduler_runner,
            now=now,
        )

        if diagnostic is not None and target_cycle_number is not None:
            cycle = (
                db.query(ShadowRunCycle)
                .filter(
                    ShadowRunCycle.session_id == int(session_id),
                    ShadowRunCycle.cycle_number == int(target_cycle_number),
                    ShadowRunCycle.status == "completed",
                )
                .first()
            )
            if cycle is not None:
                snapshot = dict(cycle.reconciliation_snapshot or {})
                snapshot[DAY38_POLICY_SNAPSHOT_KEY] = diagnostic
                cycle.reconciliation_snapshot = snapshot
                db.flush()
        return result

    wrapped._day38_cycle_wrapper = True
    wrapped._day38_cycle_original = original
    full_stack_shadow.execute_shadow_cycle = wrapped

    # The Celery task module imports the function by name. Patch that local reference
    # too when it has already been imported before worker_init/main integration runs.
    try:
        from app.tasks import shadow_runs as shadow_tasks
    except Exception:
        shadow_tasks = None
    if shadow_tasks is not None:
        shadow_tasks.execute_shadow_cycle = wrapped

    _WORKER_INSTALLED = True


def install_day38_api_integration() -> None:
    """Install Day 38 API preflight and ORM launch guards."""

    _install_model_guards()
    _install_api_preflight()


def install_day38_worker_integration() -> None:
    """Install diagnostic-only Day 38 policy telemetry in the shadow worker."""

    _install_worker_cycle_telemetry()


__all__ = [
    "DAY38_POLICY_SNAPSHOT_KEY",
    "DAY38_POLICY_TELEMETRY_VERSION",
    "install_day38_api_integration",
    "install_day38_worker_integration",
    "production_policy_diagnostic",
]
