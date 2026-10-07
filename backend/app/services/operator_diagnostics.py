"""Build the read-only owner-facing OneHost diagnostics report."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Mapping, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    SubmissionEvidence,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.user import User
from app.services.operations_settings import get_operations_settings
from app.version import APP_VERSION


Probe = Callable[[], Mapping[str, Any]]


def _count(db: Session, user_id: int, *states: str) -> int:
    return (
        db.query(Application.id)
        .filter(
            Application.user_id == user_id,
            Application.automation_state.in_(states),
        )
        .count()
    )


def _database_is_healthy(db: Session, user_id: int) -> bool:
    try:
        db.query(User.id).filter(User.id == user_id).one()
    except SQLAlchemyError:
        return False
    return True


def _probe_result(
    probe: Optional[Probe],
    *,
    default: Mapping[str, Any],
) -> Dict[str, Any]:
    if probe is None:
        return dict(default)
    try:
        return dict(probe())
    except Exception as exc:
        return {
            "ok": False,
            "reason": "probe_failed",
            "error_type": type(exc).__name__,
        }


def _status_label(result: Mapping[str, Any], ready: str, not_ready: str) -> str:
    state = result.get("ok")
    if state is True:
        return ready
    if state is False:
        return not_ready
    return "Unverified"


def _database_label(database_ok: bool) -> str:
    return {True: "Healthy", False: "Unhealthy"}[bool(database_ok)]


def _safety_labels(
    *,
    autopilot: bool,
    real_submit: bool,
    kill_armed: bool,
) -> Dict[str, str]:
    return {
        "autopilot": {True: "ON", False: "OFF"}[bool(autopilot)],
        "real_submit": {True: "ON", False: "OFF"}[bool(real_submit)],
        "kill_switch": {True: "ARMED", False: "DISARMED"}[bool(kill_armed)],
    }


def _evidence_count(db: Session, user_id: int) -> int:
    return (
        db.query(SubmissionEvidence.id)
        .join(
            Application,
            Application.id == SubmissionEvidence.application_id,
        )
        .filter(
            Application.user_id == user_id,
            SubmissionEvidence.is_sufficient.is_(True),
        )
        .count()
    )


def _handoff_count(db: Session, user_id: int) -> int:
    active_states = [
        HandoffSessionStatus.awaiting_user.value,
        HandoffSessionStatus.claimed.value,
        HandoffSessionStatus.ready_to_resume.value,
    ]
    return (
        db.query(ManualHandoffSession.id)
        .filter(
            ManualHandoffSession.user_id == user_id,
            ManualHandoffSession.status.in_(active_states),
        )
        .count()
    )


def _application_counts(db: Session, user_id: int) -> Dict[str, int]:
    confirmed_state_count = _count(
        db,
        user_id,
        ApplicationAutomationState.confirmed.value,
    )
    applied_without_confirmed_state = (
        db.query(Application.id)
        .filter(
            Application.user_id == user_id,
            Application.status == ApplicationStatus.applied,
            Application.automation_state
            != ApplicationAutomationState.confirmed.value,
        )
        .count()
    )
    return {
        "ready": _count(
            db,
            user_id,
            ApplicationAutomationState.ready_to_apply.value,
        ),
        "needs_review": _count(
            db,
            user_id,
            ApplicationAutomationState.needs_review.value,
        ),
        "applying": _count(
            db,
            user_id,
            ApplicationAutomationState.applying.value,
        ),
        "confirmed": confirmed_state_count + applied_without_confirmed_state,
    }


def _actionable_errors(
    *,
    onehost: Mapping[str, Any],
    worker: Mapping[str, Any],
    browser: Mapping[str, Any],
    database_ok: bool,
    real_submit: bool,
    kill_armed: bool,
) -> list[Dict[str, str]]:
    errors: list[Dict[str, str]] = []
    checks = (
        (
            onehost.get("ok") is not True,
            "onehost_not_connected",
            "Check the OneHost API readiness probe.",
        ),
        (
            worker.get("ok") is not True,
            "worker_unverified",
            "Verify the OneHost Celery worker healthcheck.",
        ),
        (
            browser.get("ok") is not True,
            "browser_unverified",
            "Verify the owned OneHost browser profile and process.",
        ),
        (
            not database_ok,
            "database_unhealthy",
            "Restore Postgres health before application work.",
        ),
        (
            real_submit,
            "real_submit_enabled",
            "Turn real submit off. Diagnostics never grants submit.",
        ),
        (
            not kill_armed,
            "kill_switch_disarmed",
            "Arm AUTOMATION_GLOBAL_KILL_SWITCH before supervised execution.",
        ),
    )
    for blocked, code, action in checks:
        if blocked:
            errors.append({"code": code, "action": action})
    return errors


def _runtime_probe_snapshot(
    *,
    onehost_probe: Optional[Probe],
    worker_probe: Optional[Probe],
    browser_probe: Optional[Probe],
) -> tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    runtime_mode = str(os.environ.get("JOBTOMATIK_RUNTIME_MODE") or "").strip()
    onehost = _probe_result(
        onehost_probe,
        default={"ok": runtime_mode.lower() == "onehost"},
    )
    worker = _probe_result(
        worker_probe,
        default={"ok": None, "reason": "worker_unverified"},
    )
    browser = _probe_result(
        browser_probe,
        default={"ok": None, "reason": "browser_unverified"},
    )
    return runtime_mode, onehost, worker, browser


def _owner_diagnostic_snapshot(db: Session, user_id: int) -> Dict[str, Any]:
    evidence_count = _evidence_count(db, user_id)
    return {
        "database_ok": _database_is_healthy(db, user_id),
        "applications": _application_counts(db, user_id),
        "handoff_count": _handoff_count(db, user_id),
        "evidence_count": evidence_count,
    }


def build_operator_diagnostics(
    db: Session,
    user: User,
    *,
    onehost_probe: Optional[Probe] = None,
    worker_probe: Optional[Probe] = None,
    browser_probe: Optional[Probe] = None,
) -> Dict[str, Any]:
    """Return a truthful read-only status snapshot for the authenticated owner."""
    settings = get_settings()
    operations = get_operations_settings()
    runtime_mode, onehost, worker, browser = _runtime_probe_snapshot(
        onehost_probe=onehost_probe,
        worker_probe=worker_probe,
        browser_probe=browser_probe,
    )
    owner = _owner_diagnostic_snapshot(db, user.id)
    real_submit = bool(settings.allow_real_application_submit)
    autopilot = bool(operations.autopilot_enabled)
    kill_armed = operations.global_kill_switch is True
    evidence_count = owner["evidence_count"]
    return {
        "product": "JOBTOMATIK",
        "version": APP_VERSION,
        "runtime_mode": runtime_mode or "unspecified",
        "backend_compatible": True,
        "grants_submit": False,
        "retired_controls": ["android_native_chrome", "termux_browser", "adb"],
        "status": {
            "onehost": _status_label(onehost, "Connected", "Not connected"),
            "worker": _status_label(worker, "Ready", "Not ready"),
            "browser": _status_label(browser, "Ready", "Not ready"),
            "database": _database_label(owner["database_ok"]),
        },
        "applications": owner["applications"],
        "handoff": {"open": owner["handoff_count"]},
        "evidence": {
            "sufficient": evidence_count,
            "available": evidence_count > 0,
        },
        "safety": _safety_labels(
            autopilot=autopilot,
            real_submit=real_submit,
            kill_armed=kill_armed,
        ),
        "actionable_errors": _actionable_errors(
            onehost=onehost,
            worker=worker,
            browser=browser,
            database_ok=owner["database_ok"],
            real_submit=real_submit,
            kill_armed=kill_armed,
        ),
        "recovery_controls": [
            "refresh_diagnostics",
            "export_diagnostics_bundle",
        ],
    }


def render_operator_status(report: Mapping[str, Any]) -> str:
    """Render the compact owner status board as plain text."""
    status = report.get("status") or {}
    applications = report.get("applications") or {}
    safety = report.get("safety") or {}
    lines = [
        "JOBTOMATIK",
        "",
        f"OneHost        {status.get('onehost', 'Not connected')}",
        f"Worker         {status.get('worker', 'Unverified')}",
        f"Browser        {status.get('browser', 'Unverified')}",
        f"Database       {status.get('database', 'Unhealthy')}",
        "",
        "Applications",
        f"Ready          {applications.get('ready', 0)}",
        f"Needs review   {applications.get('needs_review', 0)}",
        f"Applying       {applications.get('applying', 0)}",
        f"Confirmed      {applications.get('confirmed', 0)}",
        "",
        "Safety",
        f"Autopilot      {safety.get('autopilot', 'OFF')}",
        f"Real Submit    {safety.get('real_submit', 'OFF')}",
        f"Kill Switch    {safety.get('kill_switch', 'DISARMED')}",
    ]
    return "\n".join(lines) + "\n"
