"""Runtime composition for Day 30 queue policy.

Production scheduler admission counts every prior application. Worker-time rechecks must
exclude the application currently being processed, otherwise a boundary cap of one can
admit the first item and then block that same item after its row is created.

The explicit no-submit shadow profile keeps its inherited Phase 11 semantics: Day 30
business/suitability filters are production queue controls and do not override the
existing shadow-only bypass. Hard shadow safety remains enforced by the inherited gate.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Callable

from app.models.application import Application, ApplicationStatus
from app.models.job import Job
from app.services import application_queue_policy as queue_policy
from app.services import unattended_policy
from app.services.operations_policy import AutomationDecision, platform_key_for_url


_CURRENT_APPLICATION_ID: ContextVar[int | None] = ContextVar(
    "day30_current_application_id",
    default=None,
)
_COUNTER_HOOKS_INSTALLED = False


def current_application_id() -> int | None:
    return _CURRENT_APPLICATION_ID.get()


def _unique_active_application_id(db, user_id: int, job_id: int) -> int | None:
    rows = (
        db.query(Application.id)
        .filter(
            Application.user_id == int(user_id),
            Application.job_id == int(job_id),
            Application.status.in_([ApplicationStatus.pending, ApplicationStatus.applying]),
        )
        .order_by(Application.id.desc())
        .limit(2)
        .all()
    )
    if len(rows) != 1:
        return None
    return int(rows[0][0])


def install_context_aware_cap_helpers() -> None:
    """Make inherited and Day 30 counters exclude only the active worker application.

    With no worker context these wrappers are exact pass-throughs, so scheduler-time
    admission continues to count every existing application. Explicit exclusion passed
    by the inherited shadow gate remains authoritative over the context fallback.
    """

    global _COUNTER_HOOKS_INSTALLED
    if _COUNTER_HOOKS_INSTALLED:
        return

    original_autopilot = unattended_policy.evaluate_autopilot_policy
    original_employer_count = unattended_policy._employer_daily_count
    original_platform_count = queue_policy._platform_daily_count

    def context_autopilot(
        db,
        user,
        now=None,
        *,
        exclude_application_id=None,
        policy_profile="production",
    ):
        effective_exclusion = (
            exclude_application_id
            if exclude_application_id is not None
            else current_application_id()
        )
        return original_autopilot(
            db,
            user,
            now,
            exclude_application_id=effective_exclusion,
            policy_profile=policy_profile,
        )

    def context_employer_count(
        db,
        user_id,
        employer_name,
        now,
        *,
        exclude_application_id=None,
    ):
        effective_exclusion = (
            exclude_application_id
            if exclude_application_id is not None
            else current_application_id()
        )
        return original_employer_count(
            db,
            user_id,
            employer_name,
            now,
            exclude_application_id=effective_exclusion,
        )

    def context_platform_count(db, user_id: int, platform: str, now: datetime) -> int:
        count = int(original_platform_count(db, user_id, platform, now))
        application_id = current_application_id()
        if application_id is None or count <= 0:
            return count

        cutoff = now - timedelta(days=1)
        row = (
            db.query(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .filter(
                Application.id == int(application_id),
                Application.user_id == int(user_id),
                Application.created_at >= cutoff,
            )
            .first()
        )
        if row is None:
            return count
        application, job = row
        url = str(application.application_target_url or job.url or "")
        if platform_key_for_url(url) != platform:
            return count
        return max(0, count - 1)

    unattended_policy.evaluate_autopilot_policy = context_autopilot
    unattended_policy._employer_daily_count = context_employer_count
    queue_policy._platform_daily_count = context_platform_count
    _COUNTER_HOOKS_INSTALLED = True


def _attach_audit_id(
    decision: AutomationDecision,
    audit_id: int | None,
) -> AutomationDecision:
    if audit_id is None:
        return decision
    return AutomationDecision(
        decision.allowed,
        decision.code,
        decision.reason,
        {**dict(decision.metadata or {}), "policy_audit_run_id": audit_id},
    )


def build_shared_evaluator(
    base_evaluator: Callable[..., AutomationDecision],
) -> Callable[..., AutomationDecision]:
    """Compose the inherited gate with Day 30 production constraints.

    A validated no-submit shadow candidate is returned unchanged. The inherited gate
    already records that its suitability/business filters were intentionally bypassed;
    applying Day 30 production filters after that decision would silently invalidate
    the Phase 11 shadow contract.
    """

    def evaluate(db, user, job: Job, now: datetime | None = None) -> AutomationDecision:
        current = now or datetime.utcnow()
        base = base_evaluator(db, user, job, now=current)

        if bool((base.metadata or {}).get("shadow_policy_candidate")):
            return base

        if not base.allowed:
            audit_id = queue_policy._audit_decision(
                db,
                user,
                job,
                base,
                stage="scheduler_or_worker",
                now=current,
            )
            return _attach_audit_id(base, audit_id)

        raw = dict(job.raw_data or {})
        target_url = str(raw.get("selected_apply_url") or job.url or "")
        platform = platform_key_for_url(target_url)
        day30 = queue_policy.evaluate_day30_constraints(
            db,
            user,
            job,
            now=current,
            platform=platform,
        )
        merged = AutomationDecision(
            day30.allowed,
            day30.code,
            day30.reason,
            {
                **dict(base.metadata or {}),
                **dict(day30.metadata or {}),
                "inherited_policy_code": base.code,
            },
        )
        audit_id = queue_policy._audit_decision(
            db,
            user,
            job,
            merged,
            stage="scheduler_or_worker",
            now=current,
        )
        return _attach_audit_id(merged, audit_id)

    return evaluate


def build_worker_evaluator(
    shared_evaluator: Callable[..., AutomationDecision],
) -> Callable[..., AutomationDecision]:
    """Add a narrow current-application context around worker-time policy rechecks."""

    def evaluate(db, user, job: Job, now: datetime | None = None) -> AutomationDecision:
        if user.id is None or job.id is None:
            return shared_evaluator(db, user, job, now=now)
        application_id = _unique_active_application_id(
            db,
            int(user.id),
            int(job.id),
        )
        if application_id is None:
            # Ambiguous/missing current application means no exclusion. This fails
            # conservatively at cap boundaries instead of under-counting applications.
            return shared_evaluator(db, user, job, now=now)
        token = _CURRENT_APPLICATION_ID.set(application_id)
        try:
            return shared_evaluator(db, user, job, now=now)
        finally:
            _CURRENT_APPLICATION_ID.reset(token)

    return evaluate
