#!/usr/bin/env python3
from __future__ import annotations

"""Shadow qualification canary with terminal worker failure diagnostics.

The established orchestration remains byte-for-byte in
``run_shadow_qualification_canary_base``. This facade fixes the physical
Campaign #5 diagnostic gap: once the one real Application has already entered
``failed`` after a worker attempt, the canary must surface that failure
immediately instead of waiting the remaining eight-minute timeout.

The delegated base still performs the real qualification contract:
``run_job_search.apply_async`` -> ``_run_scheduler_cycle_for_user`` with
``shadow_application_limit=1`` -> durable Application -> applications queue ->
real worker/browser path. No mock candidate or certification shortcut exists.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import run_shadow_qualification_canary_base as _base  # noqa: E402

for _name in dir(_base):
    if _name.startswith("__") or _name in globals():
        continue
    globals()[_name] = getattr(_base, _name)

_BASE_APPLICATION_SNAPSHOT = _base._application_snapshot


def _application_snapshot(db, application_id: int) -> dict[str, Any]:
    """Include the worker's terminal event payload in qualification evidence."""

    snapshot = _BASE_APPLICATION_SNAPSHOT(db, application_id)
    if snapshot.get("missing"):
        return snapshot

    events = (
        db.query(ApplicationEvent)
        .filter(ApplicationEvent.application_id == int(application_id))
        .order_by(ApplicationEvent.id.asc())
        .all()
    )
    failed_event = next(
        (
            event
            for event in reversed(events)
            if str(event.event_type or "") == "application_attempt_failed"
        ),
        None,
    )
    if failed_event is not None:
        payload = dict(failed_event.payload or {})
        snapshot["worker_failure_event_payload"] = payload
        snapshot["worker_failure_error"] = str(payload.get("error") or "")[:800]
    else:
        snapshot["worker_failure_event_payload"] = None
        snapshot["worker_failure_error"] = None
    return snapshot


def _wait_for_application_path(
    db,
    application_id: int,
    session_id: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Wait for a safe browser boundary, but never wait behind a terminal failure."""

    deadline = time.monotonic() + timeout_seconds
    last = _application_snapshot(db, application_id)
    while time.monotonic() < deadline:
        db.expire_all()
        last = _application_snapshot(db, application_id)
        if last.get("consequential_state_observed"):
            raise RuntimeError(
                "Safety violation: canary application entered a consequential/submitted state"
            )

        attempts = int(last.get("submission_attempt_count") or 0)
        if (
            attempts >= 1
            and str(last.get("automation_state") or "")
            == ApplicationAutomationState.failed.value
        ):
            raise RuntimeError(
                "Canary worker application failed before reaching an intentional dry-run or "
                "human boundary: "
                + json.dumps(last, sort_keys=True)[:1800]
            )

        if (
            attempts >= 1
            and last.get("browser_or_form_path_observed") is True
            and last.get("safe_terminal") is True
        ):
            return last

        session = (
            db.query(ShadowRunSession)
            .filter(ShadowRunSession.id == int(session_id))
            .first()
        )
        if session is not None and session.status == "failed":
            raise RuntimeError(
                "Canary shadow session failed during worker execution: "
                f"{session.failure_reason or 'unknown'}"
            )
        time.sleep(2)

    raise RuntimeError(
        "Canary timed out before the real worker/browser path reached an intentional dry-run "
        "or human boundary: "
        + json.dumps(last, sort_keys=True)[:1800]
    )


_PATCHABLE_BASE_SEAMS = (
    "get_settings",
    "SessionLocal",
    "current_revision",
    "canary_receipt_path",
    "runtime_acceptance_status",
    "runtime_fingerprint",
    "write_receipt",
    "build_search_plan",
    "campaign_policy_readiness",
    "_run_scheduler_cycle_for_user",
    "run_job_search",
)


def _sync_base_seams() -> None:
    """Keep established test/operator monkeypatch seams on the public module."""

    for name in _PATCHABLE_BASE_SEAMS:
        if name in globals():
            setattr(_base, name, globals()[name])
    # These two are intentionally resolved on every invocation so a focused
    # test can replace the public wait/snapshot seam without touching the base.
    _base._application_snapshot = globals()["_application_snapshot"]
    _base._wait_for_application_path = globals()["_wait_for_application_path"]


def run_canary(*args, **kwargs):
    _sync_base_seams()
    return _base.run_canary(*args, **kwargs)


CANARY_TIMEOUT_SECONDS = _base.CANARY_TIMEOUT_SECONDS


def main() -> int:
    _sync_base_seams()
    # Base main resolves its own run_canary global; point it at this wrapper so
    # CLI and authenticated API execution share the same patched seams.
    original_run_canary = _base.run_canary
    try:
        _base.run_canary = run_canary
        return _base.main()
    finally:
        _base.run_canary = original_run_canary


if __name__ == "__main__":
    raise SystemExit(main())
