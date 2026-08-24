"""Worker-time installation for the Day 30 application queue policy extension."""

from __future__ import annotations

from app.services.application_queue_policy_runtime import (
    build_shared_evaluator,
    build_worker_evaluator,
    install_context_aware_cap_helpers,
)


_INSTALLED = False


def install_application_queue_policy() -> None:
    """Patch scheduler and worker consumers without weakening inherited policy.

    Scheduler admission uses the shared evaluator with normal counts. The unattended
    worker uses the same evaluator inside a narrow current-application context so its
    recheck excludes only the row it is currently processing from global, employer,
    and per-platform caps. Explicit no-submit shadow semantics remain inherited.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import scheduler_policy, unattended_policy
    from app.tasks import unattended as unattended_tasks

    install_context_aware_cap_helpers()
    shared = build_shared_evaluator(unattended_policy.evaluate_unattended_job_policy)
    worker = build_worker_evaluator(shared)
    scheduler_policy.evaluate_unattended_job_policy = shared
    unattended_tasks.evaluate_unattended_job_policy = worker
    _INSTALLED = True
