"""Compatibility bridge for LinkedIn jobs saved before browser Apply routing.

Older discovery records store ``unsupported_job_board`` in ``Job.raw_data``.
The submission task trusts that cached method and therefore never reaches the
browser navigator. This worker integration clears only that stale LinkedIn
classification so the normal resolver can route the listing through the
outbound employer Apply link.

A successful re-route also dismisses the superseded ``unsupported_platform``
manual-review record. Without that cleanup the frontend keeps showing the old
LinkedIn discovery-only card even after a later attempt reaches the employer
application flow.
"""

from __future__ import annotations

from datetime import datetime
from functools import wraps
from typing import Any, Dict

from app.models.application import (
    Application,
    ApplicationEvent,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.services.apply_resolver import is_browser_resolvable_job_board_url


def _needs_linkedin_reresolution(job: Any) -> bool:
    raw: Dict[str, Any] = dict(getattr(job, "raw_data", None) or {})
    return (
        raw.get("application_method") == "unsupported_job_board"
        and is_browser_resolvable_job_board_url(getattr(job, "url", "") or "")
    )


def _is_discovery_only_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    error = str(result.get("error") or "").lower()
    actions = " ".join(
        str(item.get("action") or "").lower()
        for item in result.get("log") or []
        if isinstance(item, dict)
    )
    return (
        "discovery-only" in error
        or "discovery only" in error
        or "unsupported_job_board" in actions
    )


def _dismiss_superseded_linkedin_reviews(
    applications_module: Any,
    application_id: int,
    result: Any,
) -> int:
    """Dismiss only the stale LinkedIn unsupported-platform review.

    A new employer-form blocker, such as login, CAPTCHA, or an unanswered field,
    is created by the normal task path and remains open. This cleanup touches only
    the earlier discovery-only review once the cached LinkedIn method was actually
    reclassified.
    """
    if _is_discovery_only_result(result):
        return 0

    db = applications_module.SessionLocal()
    try:
        application = db.query(Application).filter(
            Application.id == application_id
        ).first()
        if not application:
            return 0

        job = db.query(Job).filter(Job.id == application.job_id).first()
        if not job:
            return 0

        raw = dict(job.raw_data or {})
        if raw.get("previous_application_method") != "unsupported_job_board":
            return 0

        reviews = (
            db.query(ManualReviewTask)
            .filter(
                ManualReviewTask.application_id == application.id,
                ManualReviewTask.reason_code == ManualReviewReason.unsupported_platform.value,
                ManualReviewTask.status.in_([
                    ManualReviewStatus.open.value,
                    ManualReviewStatus.in_progress.value,
                ]),
            )
            .all()
        )
        if not reviews:
            return 0

        now = datetime.utcnow()
        for review in reviews:
            review.status = ManualReviewStatus.dismissed.value
            review.resolved_at = now
            review.resolution_notes = (
                "Superseded by a later LinkedIn Apply attempt that was routed "
                "into the employer application flow."
            )

        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="stale_linkedin_review_dismissed",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "review_count": len(reviews),
                "previous_application_method": "unsupported_job_board",
                "current_application_method": raw.get("application_method"),
            },
        ))
        db.commit()
        return len(reviews)
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


def install_linkedin_apply_resolution() -> None:
    """Patch cached-method resolution and stale-review cleanup once per worker."""
    import app.tasks.applications as applications_module

    original_ensure = applications_module._ensure_application_method
    if not getattr(original_ensure, "_jobtomatik_linkedin_apply_resolution", False):

        @wraps(original_ensure)
        def resolve_cached_linkedin_method(job: Any):
            if _needs_linkedin_reresolution(job):
                raw = dict(job.raw_data or {})
                raw.pop("application_method", None)
                raw.pop("selected_apply_url", None)
                raw["previous_application_method"] = "unsupported_job_board"
                raw["reason"] = "Re-resolving LinkedIn listing through outbound Apply navigation"
                job.raw_data = raw
            return original_ensure(job)

        resolve_cached_linkedin_method._jobtomatik_linkedin_apply_resolution = True
        applications_module._ensure_application_method = resolve_cached_linkedin_method

    task = applications_module.submit_application_task
    original_run = task.run
    if getattr(original_run, "_jobtomatik_linkedin_review_cleanup", False):
        return

    @wraps(original_run)
    def run_with_linkedin_review_cleanup(
        application_id: int,
        dry_run: bool = True,
        **kwargs,
    ):
        result = original_run(application_id, dry_run=dry_run, **kwargs)
        _dismiss_superseded_linkedin_reviews(
            applications_module,
            application_id,
            result,
        )
        return result

    run_with_linkedin_review_cleanup._jobtomatik_linkedin_review_cleanup = True
    task.run = run_with_linkedin_review_cleanup


__all__ = [
    "_dismiss_superseded_linkedin_reviews",
    "_is_discovery_only_result",
    "_needs_linkedin_reresolution",
    "install_linkedin_apply_resolution",
]
