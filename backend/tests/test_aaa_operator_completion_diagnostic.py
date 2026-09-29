"""Temporary CI diagnostic for the PR #583 post-fill handoff failure.

This file intentionally fails with a compact result summary so the synthetic browser
run can distinguish boundary injection from retained-handoff persistence failures.
It must be removed before the repair PR is considered ready.
"""

from app.tasks import operator_assisted as prepare_task
from tests.test_operator_assisted_completion import browser_env, env  # noqa: F401


def test_operator_completion_handoff_diagnostic(browser_env):
    test_env = browser_env
    with test_env.monkeypatch.context() as worker:
        worker.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")
        result = prepare_task.prepare_operator_assisted_application_task.run(test_env.app_id)

    review_items = list(result.get("review_items") or []) if isinstance(result, dict) else []
    log = list(result.get("log") or []) if isinstance(result, dict) else []
    snapshot = dict(result.get("handoff_snapshot") or {}) if isinstance(result, dict) else {}
    summary = {
        "success": result.get("success") if isinstance(result, dict) else None,
        "ready_to_submit": result.get("ready_to_submit") if isinstance(result, dict) else None,
        "requires_manual_review": result.get("requires_manual_review") if isinstance(result, dict) else None,
        "error": result.get("error") if isinstance(result, dict) else repr(result),
        "handoff_public_id": result.get("handoff_public_id") if isinstance(result, dict) else None,
        "handoff_snapshot_present": bool(snapshot),
        "review_reasons": [str(item.get("reason_code") or "") for item in review_items],
        "review_details": [dict(item.get("details") or {}) for item in review_items],
        "log_tail": log[-8:],
        "launched_targets": list(getattr(test_env, "launched", [])),
    }
    raise AssertionError(summary)
