"""Worker-time installation for the Day 30 application queue policy extension."""

from __future__ import annotations

from app.services.application_queue_policy import build_policy_evaluator


_INSTALLED = False


def install_application_queue_policy() -> None:
    """Patch the two runtime consumers of the inherited unattended evaluator.

    The scheduler ranks through ``scheduler_policy.evaluate_unattended_job_policy``;
    the unattended worker imports the same evaluator directly. Patching both module
    globals keeps the Day 30 checks identical before queue creation and immediately
    before browser execution without mutating the inherited base gate itself.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import scheduler_policy, unattended_policy
    from app.tasks import unattended as unattended_tasks

    wrapped = build_policy_evaluator(unattended_policy.evaluate_unattended_job_policy)
    scheduler_policy.evaluate_unattended_job_policy = wrapped
    unattended_tasks.evaluate_unattended_job_policy = wrapped
    _INSTALLED = True
