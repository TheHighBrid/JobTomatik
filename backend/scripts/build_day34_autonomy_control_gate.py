from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.config import get_settings
from app.services.operator_autonomy_control import (
    AUTONOMY_CONTROL_KEY,
    MODE_DRAINING,
    MODE_PAUSED,
    MODE_RUNNING,
    autonomy_control_state,
    scheduler_control_decision,
    worker_control_decision,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
VERSION = "day34-autonomy-control-gate-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _user(mode: str | None):
    settings = {}
    if mode is not None:
        settings[AUTONOMY_CONTROL_KEY] = {"mode": mode}
    return SimpleNamespace(id=34, automation_settings=settings)


def build_gate(verification_commit: str) -> dict:
    page = REPO_ROOT / "frontend/src/pages/AutonomyCenter.jsx"
    api = REPO_ROOT / "backend/app/api/autonomy_control.py"
    control = BACKEND_ROOT / "app/services/operator_autonomy_control.py"
    integration = BACKEND_ROOT / "app/services/operator_autonomy_control_integration.py"
    mobile_nav = REPO_ROOT / "frontend/src/components/MobileNav.jsx"
    android_workflow = REPO_ROOT / ".github/workflows/android-apk.yml"

    page_text = page.read_text(encoding="utf-8")
    api_text = api.read_text(encoding="utf-8")
    integration_text = integration.read_text(encoding="utf-8")
    mobile_text = mobile_nav.read_text(encoding="utf-8")
    android_text = android_workflow.read_text(encoding="utf-8")

    running = _user(MODE_RUNNING)
    paused = _user(MODE_PAUSED)
    draining = _user(MODE_DRAINING)
    invalid = _user("invalid-mode")
    core = get_settings()

    contract = {
        "running_allows_scheduler_admission": scheduler_control_decision(running)["allowed"] is True,
        "pause_blocks_scheduler_admission": scheduler_control_decision(paused)["allowed"] is False,
        "pause_blocks_prebrowser_worker": worker_control_decision(paused)["allowed"] is False,
        "drain_blocks_new_scheduler_admission": scheduler_control_decision(draining)["allowed"] is False,
        "drain_allows_existing_prebrowser_work": worker_control_decision(draining)["allowed"] is True,
        "invalid_state_fails_closed": (
            autonomy_control_state(invalid)["valid"] is False
            and autonomy_control_state(invalid)["mode"] == MODE_PAUSED
        ),
        "control_api_has_no_submit_route": "/submit" not in api_text,
        "ui_has_no_direct_live_submit_control": "No direct live-submit control." in page_text,
        "ui_exposes_pause_drain_resume_reject": all(term in page_text for term in ("Pause", "Drain", "Resume", "Reject")),
        "ui_exposes_required_domains": all(
            term in page_text
            for term in (
                "Readiness",
                "Active adapters",
                "Caps & quiet hours",
                "Queue",
                "Blockers",
                "Handoffs",
                "Evidence",
                "Kill switches",
            )
        ),
        "offline_reconnect_bound": all(
            term in page_text
            for term in (
                "window.addEventListener('online'",
                "window.addEventListener('offline'",
                "aria-live=\"polite\"",
            )
        ),
        "android_one_tap_control_route": "to: '/autonomy'" in mobile_text and "label: 'Control'" in mobile_text,
        "worker_runtime_installs_operator_gate": "install_operator_autonomy_control" in integration_text,
        "android_lint_and_assemble_required": "lintDebug assembleDebug" in android_text,
        "android_platform_35_required": 'platforms;android-35' in android_text,
    }

    gate = {
        "version": VERSION,
        "verification_commit": verification_commit,
        "gate_passed": all(contract.values()),
        "runtime_safety": {
            "autopilot_enabled": False,
            "real_submission_enabled": bool(core.allow_real_application_submit),
            "real_followup_enabled": bool(core.allow_real_followup_send),
            "control_submission_authorized": False,
        },
        "contract": contract,
        "source_digests": {
            "autonomy_page_sha256": _sha256(page),
            "autonomy_api_sha256": _sha256(api),
            "operator_control_sha256": _sha256(control),
            "operator_integration_sha256": _sha256(integration),
            "mobile_nav_sha256": _sha256(mobile_nav),
            "android_workflow_sha256": _sha256(android_workflow),
        },
    }
    if gate["runtime_safety"]["real_submission_enabled"] is not False:
        gate["gate_passed"] = False
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_gate(args.verification_commit)
    target = Path(args.output)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["gate_passed"]:
        raise SystemExit("Day 34 autonomy control gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
