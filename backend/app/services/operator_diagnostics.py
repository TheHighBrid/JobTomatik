"""Owner-facing OneHost status board.

This is read-only. It does not submit, retry a live application, or expose
Android/native-Chrome controls.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Mapping, Optional

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
        .filter(Application.user_id == user_id, Application.automation_state.in_(states))
        .count()
    )


def build_operator_diagnostics(
    db: Session,
    user: User,
    *,
    onehost_probe: Optional[Probe] = None,
    worker_probe: Optional[Probe] = None,
    browser_probe: Optional[Probe] = None,
) -> Dict[str, Any]:
    settings = get_settings()
    operations = get_operations_settings()
    database_ok = True
    try:
        db.query(User.id).filter(User.id == user.id).one()
    except Exception:
        database_ok = False
    onehost = dict(onehost_probe() if onehost_probe else {"ok": os.environ.get("JOBTOMATIK_RUNTIME_MODE") == "onehost"})
    worker = dict(worker_probe() if worker_probe else {"ok": False, "reason": "worker_unverified"})
    browser = dict(browser_probe() if browser_probe else {"ok": False, "reason": "browser_unverified"})
    evidence_count = (
        db.query(SubmissionEvidence.id)
        .join(Application, Application.id == SubmissionEvidence.application_id)
        .filter(Application.user_id == user.id, SubmissionEvidence.is_sufficient.is_(True))
        .count()
    )
    handoff_count = (
        db.query(ManualHandoffSession.id)
        .filter(
            ManualHandoffSession.user_id == user.id,
            ManualHandoffSession.status.in_([
                HandoffSessionStatus.awaiting_user.value,
                HandoffSessionStatus.claimed.value,
                HandoffSessionStatus.ready_to_resume.value,
            ]),
        )
        .count()
    )
    real_submit = bool(settings.allow_real_application_submit)
    autopilot = bool(operations.autopilot_enabled)
    kill_armed = operations.global_kill_switch is True
    errors = []
    if not onehost.get("ok"):
        errors.append({"code": "onehost_not_connected", "action": "Check the OneHost API readiness probe."})
    if not worker.get("ok"):
        errors.append({"code": "worker_not_ready", "action": "Restart the OneHost worker and refresh diagnostics."})
    if not browser.get("ok"):
        errors.append({"code": "browser_not_ready", "action": "Check the OneHost browser profile. Do not use native Chrome."})
    if not database_ok:
        errors.append({"code": "database_unhealthy", "action": "Restore the Postgres volume before any application work."})
    if real_submit:
        errors.append({"code": "real_submit_enabled", "action": "Turn real submit off. Diagnostics never grants submit."})
    if not kill_armed:
        errors.append({"code": "kill_switch_disarmed", "action": "Arm AUTOMATION_GLOBAL_KILL_SWITCH before supervised execution."})
    return {
        "product": "JOBTOMATIK",
        "version": APP_VERSION,
        "runtime_mode": os.environ.get("JOBTOMATIK_RUNTIME_MODE") or "unspecified",
        "backend_compatible": True,
        "grants_submit": False,
        "retired_controls": ["android_native_chrome", "termux_browser", "adb"],
        "status": {
            "onehost": "Connected" if onehost.get("ok") else "Not connected",
            "worker": "Ready" if worker.get("ok") else "Not ready",
            "browser": "Ready" if browser.get("ok") else "Not ready",
            "database": "Healthy" if database_ok else "Unhealthy",
        },
        "applications": {
            "ready": _count(db, user.id, ApplicationAutomationState.ready_to_apply.value),
            "needs_review": _count(db, user.id, ApplicationAutomationState.needs_review.value),
            "applying": _count(db, user.id, ApplicationAutomationState.applying.value),
            "confirmed": _count(db, user.id, ApplicationAutomationState.confirmed.value) + (
                db.query(Application.id)
                .filter(Application.user_id == user.id, Application.status == ApplicationStatus.applied, Application.automation_state != ApplicationAutomationState.confirmed.value)
                .count()
            ),
        },
        "handoff": {"open": handoff_count},
        "evidence": {"sufficient": evidence_count, "available": evidence_count > 0},
        "safety": {
            "autopilot": "OFF" if not autopilot else "ON",
            "real_submit": "OFF" if not real_submit else "ON",
            "kill_switch": "ARMED" if kill_armed else "DISARMED",
        },
        "actionable_errors": errors,
        "recovery_controls": ["refresh_diagnostics", "export_diagnostics_bundle"],
    }


def render_operator_status(report: Mapping[str, Any]) -> str:
    status = report.get("status") or {}
    applications = report.get("applications") or {}
    safety = report.get("safety") or {}
    lines = [
        "JOBTOMATIK",
        "",
        f"OneHost        {status.get('onehost', 'Not connected')}",
        f"Worker         {status.get('worker', 'Not ready')}",
        f"Browser        {status.get('browser', 'Not ready')}",
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
