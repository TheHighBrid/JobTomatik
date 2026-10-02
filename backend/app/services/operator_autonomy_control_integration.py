"""Runtime bindings for Day 34 operator pause/drain/resume controls.

The scheduler wrapper prevents new admission while paused or draining. The unattended
policy wrapper is installed only in the application worker and blocks pre-browser work
while paused or when control state is malformed. Draining intentionally permits work
that was already created before the drain request.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from app.services.operations_policy import AutomationDecision
from app.services.operator_autonomy_control import (
    scheduler_control_decision,
    worker_control_decision,
)


_INSTALLED = False


def _blocked_scheduler_result(user, decision: dict[str, Any], *, shadow_session_id=None, shadow_application_limit=None):
    return {
        "user_id": user.id,
        "skipped": True,
        "reason": decision["code"],
        "operator_control": decision,
        "searched": False,
        "applications_queued": 0,
        "application_ids_queued": [],
        "blocked_job_reasons": {decision["code"]: 1},
        "shadow_session_id": shadow_session_id,
        "shadow_application_limit": shadow_application_limit,
        "submission_authorized": False,
    }


def install_operator_autonomy_control() -> None:
    """Install idempotent process-local wrappers around scheduler and worker chokepoints."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app.tasks import scraping as scraping_tasks
    from app.tasks import unattended as unattended_tasks

    original_cycle = scraping_tasks._run_scheduler_cycle_for_user
    if not getattr(original_cycle, "_day34_operator_control_wrapper", False):
        @wraps(original_cycle)
        def controlled_cycle(
            db,
            user,
            *,
            shadow_session_id=None,
            shadow_application_limit=None,
        ):
            # Correlated shadow tests intentionally use malformed principals to prove
            # that the inherited scheduler shadow guard fails closed before ranking or
            # worker dispatch. Preserve that stronger, existing safety contract rather
            # than masking it with a Day 34 operator-control error.
            if shadow_session_id is not None and not hasattr(user, "automation_settings"):
                return original_cycle(
                    db,
                    user,
                    shadow_session_id=shadow_session_id,
                    shadow_application_limit=shadow_application_limit,
                )

            decision = scheduler_control_decision(user)
            if not decision["allowed"]:
                return _blocked_scheduler_result(
                    user,
                    decision,
                    shadow_session_id=shadow_session_id,
                    shadow_application_limit=shadow_application_limit,
                )
            return original_cycle(
                db,
                user,
                shadow_session_id=shadow_session_id,
                shadow_application_limit=shadow_application_limit,
            )

        controlled_cycle._day34_operator_control_wrapper = True
        controlled_cycle._day34_operator_control_original = original_cycle
        scraping_tasks._run_scheduler_cycle_for_user = controlled_cycle

    original_worker_policy = unattended_tasks.evaluate_unattended_job_policy
    if not getattr(original_worker_policy, "_day34_operator_control_wrapper", False):
        @wraps(original_worker_policy)
        def controlled_worker_policy(db, user, job, *args, **kwargs):
            decision = worker_control_decision(user)
            if not decision["allowed"]:
                return AutomationDecision(
                    False,
                    decision["code"],
                    decision["reason"],
                    {
                        "operator_control": True,
                        "operator_mode": decision["mode"],
                        "submission_authorized": False,
                    },
                )
            inherited = original_worker_policy(db, user, job, *args, **kwargs)
            if decision["mode"] == "draining":
                metadata = dict(inherited.metadata or {})
                metadata["operator_control"] = True
                metadata["operator_mode"] = "draining"
                return AutomationDecision(
                    inherited.allowed,
                    inherited.code,
                    inherited.reason,
                    metadata,
                )
            return inherited

        controlled_worker_policy._day34_operator_control_wrapper = True
        controlled_worker_policy._day34_operator_control_original = original_worker_policy
        unattended_tasks.evaluate_unattended_job_policy = controlled_worker_policy

    _INSTALLED = True


__all__ = ["install_operator_autonomy_control"]
