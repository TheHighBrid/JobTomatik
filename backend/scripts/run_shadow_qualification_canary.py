#!/usr/bin/env python3
"""Prove the real no-submit application path once before a timed shadow campaign.

The canary is deliberately non-certifying. It uses real discovery, the real scheduler
ranking/policy path, a real Application record, the real applications queue/worker,
and the real external-CDP browser/form runner. It is bounded to one application and
never changes adapter maturity or enables submission/outreach.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.application import (  # noqa: E402
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewTask,
)
from app.models.certification import ShadowRunSession  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.certification_scale import canonical_hash, current_revision  # noqa: E402
from app.services.full_stack_shadow import ACTIVE_SESSION_STATES  # noqa: E402
from app.services.runtime_acceptance import (  # noqa: E402
    canary_receipt_path,
    runtime_acceptance_status,
    runtime_fingerprint,
    write_receipt,
)
from app.services.scheduler_policy import build_search_plan  # noqa: E402
from app.services.shadow_qualification import campaign_policy_readiness  # noqa: E402
from app.tasks.scraping import _run_scheduler_cycle_for_user, run_job_search  # noqa: E402

CANARY_TARGET = "shadow_qualification_canary"
CANARY_TIMEOUT_SECONDS = 8 * 60
CANARY_SESSION_SECONDS = 12 * 60
BROWSER_ACTIONS = frozenset(
    {
        "navigate",
        "ats_adapter_detected",
        "application_form_not_reached",
        "browser_handoff_retained",
        "ats_final_submit_ready",
        "ats_deferred_challenge_promoted_for_handoff",
    }
)
CONSEQUENTIAL_STATES = frozenset(
    {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.confirmed.value,
    }
)
CONSEQUENTIAL_STATUSES = frozenset(
    {
        ApplicationStatus.applied.value,
        ApplicationStatus.interviewing.value,
        ApplicationStatus.offer.value,
        ApplicationStatus.rejected.value,
    }
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _user(db, requested_user_id: int | None) -> User:
    query = db.query(User).filter(User.is_active == True).order_by(User.id.asc())
    if requested_user_id is not None:
        user = query.filter(User.id == int(requested_user_id)).first()
        if user is None:
            raise RuntimeError(f"Active user not found: {requested_user_id}")
        return user
    users = query.limit(3).all()
    if len(users) != 1:
        ids = [int(item.id) for item in users]
        raise RuntimeError(
            "Qualification canary requires --user-id when the runtime has zero or multiple active users; "
            f"observed={ids}"
        )
    return users[0]


def _discovery_job_ids(discovery: dict[str, Any]) -> list[int]:
    """Normalize the exact durable Job cohort returned by real discovery."""

    result: set[int] = set()
    for value in discovery.get("job_ids") or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.add(parsed)
    return sorted(result)


def _qualification_discovery_search_params(
    search_plan: dict[str, Any],
    pre_policy: dict[str, Any],
) -> dict[str, Any]:
    """Build an ATS-only, job-interest-neutral discovery probe for qualification.

    The normal saved search plan is still required for campaign admission, but it must
    not decide whether the non-certifying infrastructure canary can reach a real ATS
    form. A configured public ATS board may have no posting that currently matches the
    user's location or keyword filters. Qualification therefore queries only the
    already-eligible account-owned ATS targets and intentionally omits suitability
    filters. The detached scheduler projection and durable canary policy context keep
    that relaxation out of timed campaigns and normal unattended execution.
    """

    targets: list[dict[str, str]] = []
    providers: list[str] = []
    seen_targets: set[tuple[str, str]] = set()
    for raw in pre_policy.get("eligible_shadow_ats_targets") or []:
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider") or "").strip().lower()
        identifier = str(raw.get("identifier") or "").strip()
        company = str(raw.get("company") or identifier).strip()
        key = (provider, identifier)
        if not provider or not identifier or key in seen_targets:
            continue
        seen_targets.add(key)
        targets.append(
            {
                "provider": provider,
                "identifier": identifier,
                "company": company or identifier,
            }
        )
        if provider not in providers:
            providers.append(provider)

    if not targets:
        raise RuntimeError(
            "Qualification requires at least one eligible account-owned public ATS target"
        )

    raw_limit = dict(search_plan.get("search_params") or {}).get("limit", 50)
    try:
        limit = max(1, min(100, int(raw_limit)))
    except (TypeError, ValueError):
        limit = 50

    return {
        "keywords": "",
        "location": "",
        "salary_min": None,
        "salary_max": None,
        "job_type": None,
        "sources": providers,
        "ats_targets": targets,
        "limit": limit,
    }


def _apply_only_scheduler_user(
    user: User,
    *,
    qualification_candidate_job_ids: list[int],
) -> SimpleNamespace:
    """Project one persisted user into an apply-only scheduler view.

    Qualification already completed and waited for the real ATS-only discovery task
    immediately before the scheduler cycle. Re-running scheduler discovery here would
    create a second external search whose result is not part of the bounded canary and
    can race the one-application qualification path. The projection is detached and
    never mutates or persists the user's automation settings.

    Minimum match is set to zero only on this detached probe so a real ATS form can be
    exercised even when no current posting matches the account's normal interest score.
    Job-interest filters are relaxed separately only when the unattended policy proves
    the durable session is this non-certifying qualification canary. Timed campaigns
    and normal scheduler users retain their persisted settings.

    The transient cohort is the exact set of durable Job ids returned by that blocking
    discovery task. The shared production ranker recognizes this attribute only on the
    detached in-process projection, so unrelated queued jobs cannot become canary
    evidence and normal scheduler users are unaffected.
    """

    automation_settings = dict(user.automation_settings or {})
    automation_settings["auto_search_enabled"] = False
    automation_settings["auto_apply_min_score"] = 0.0
    return SimpleNamespace(
        id=int(user.id),
        automation_settings=automation_settings,
        job_preferences=dict(user.job_preferences or {}),
        _qualification_candidate_job_ids=tuple(qualification_candidate_job_ids),
    )


def _create_canary_session(db, user: User, revision: str) -> ShadowRunSession:
    active = (
        db.query(ShadowRunSession)
        .filter(
            ShadowRunSession.user_id == user.id,
            ShadowRunSession.status.in_(ACTIVE_SESSION_STATES),
        )
        .first()
    )
    if active is not None:
        raise RuntimeError(f"Active shadow session already exists: {active.id}")

    now = datetime.now(timezone.utc)
    session = ShadowRunSession(
        user_id=user.id,
        candidate_revision=revision,
        target_evidence_type=CANARY_TARGET,
        requested_duration_seconds=CANARY_SESSION_SECONDS,
        cycle_interval_seconds=60,
        status="running",
        started_at=now,
        expected_end_at=now + timedelta(seconds=CANARY_SESSION_SECONDS),
        settle_deadline_at=now + timedelta(seconds=CANARY_SESSION_SECONDS + 5 * 60),
        last_heartbeat_at=now,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot={
            "version": "phase11-shadow-qualification-canary-v1",
            "candidate_revision": revision,
            "target_evidence_type": CANARY_TARGET,
            "qualification_canary": True,
            "certification_eligible": False,
            "invariants": {
                "dry_run_required": True,
                "real_submission_must_remain_disabled": True,
                "final_submit_allowed": False,
                "submission_authorized": False,
                "outreach_authorized": False,
                "adapter_maturity_mutated": False,
            },
        },
        baseline_snapshot={"qualification_canary": True},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _finish_canary_session(db, session_id: int, *, status: str, report: dict[str, Any]) -> None:
    session = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.id == int(session_id))
        .with_for_update()
        .first()
    )
    if session is None:
        return
    # A worker safety failure may have already finalized this canary. Preserve the
    # stronger failure state, but always bind the non-certifying canary report.
    if session.status in ACTIVE_SESSION_STATES:
        session.status = status
        session.failure_reason = None if status == "completed" else str(report.get("failure_reason") or "canary_failed")
        session.completed_at = datetime.now(timezone.utc)
    session.last_heartbeat_at = datetime.now(timezone.utc)
    session.final_submit_allowed = False
    session.final_report = report
    session.report_sha256 = canonical_hash(report)
    db.commit()


def _application_snapshot(db, application_id: int) -> dict[str, Any]:
    app = db.query(Application).filter(Application.id == int(application_id)).first()
    if app is None:
        return {"application_id": application_id, "missing": True}
    job = db.query(Job).filter(Job.id == app.job_id).first()
    events = (
        db.query(ApplicationEvent)
        .filter(ApplicationEvent.application_id == app.id)
        .order_by(ApplicationEvent.id.asc())
        .all()
    )
    reviews = (
        db.query(ManualReviewTask)
        .filter(ManualReviewTask.application_id == app.id)
        .order_by(ManualReviewTask.id.asc())
        .all()
    )
    log = list(app.automation_log or [])
    actions = [str(item.get("action") or "") for item in log if isinstance(item, dict)]
    event_types = [str(item.event_type or "") for item in events]
    review_reasons = [str(item.reason_code or "") for item in reviews]
    status_value = app.status.value if hasattr(app.status, "value") else str(app.status)
    automation_state = str(app.automation_state or "")
    raw = dict(job.raw_data or {}) if job is not None else {}
    browser_observed = any(action in BROWSER_ACTIONS for action in actions)
    dry_run_complete = "dry_run_completed" in event_types
    legitimate_human_boundary = (
        automation_state == ApplicationAutomationState.needs_review.value
        and browser_observed
        and bool(review_reasons)
    )
    safe_terminal = dry_run_complete or legitimate_human_boundary
    consequential = automation_state in CONSEQUENTIAL_STATES or status_value in CONSEQUENTIAL_STATUSES
    return {
        "application_id": int(app.id),
        "job_id": int(app.job_id),
        "company": str(job.company or "") if job is not None else None,
        "job_url": str(job.url or "") if job is not None else None,
        "application_method": raw.get("application_method"),
        "status": status_value,
        "automation_state": automation_state,
        "submission_attempt_count": int(app.submission_attempt_count or 0),
        "event_types": event_types,
        "review_reasons": review_reasons,
        "automation_actions": actions,
        "browser_or_form_path_observed": browser_observed,
        "dry_run_completed": dry_run_complete,
        "legitimate_human_boundary": legitimate_human_boundary,
        "safe_terminal": safe_terminal,
        "consequential_state_observed": consequential,
    }


def _wait_for_application_path(db, application_id: int, session_id: int, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last = _application_snapshot(db, application_id)
    while time.monotonic() < deadline:
        db.expire_all()
        last = _application_snapshot(db, application_id)
        if last.get("consequential_state_observed"):
            raise RuntimeError("Safety violation: canary application entered a consequential/submitted state")
        if (
            int(last.get("submission_attempt_count") or 0) >= 1
            and last.get("browser_or_form_path_observed") is True
            and last.get("safe_terminal") is True
        ):
            return last

        session = db.query(ShadowRunSession).filter(ShadowRunSession.id == int(session_id)).first()
        if session is not None and session.status == "failed":
            raise RuntimeError(
                "Canary shadow session failed during worker execution: "
                f"{session.failure_reason or 'unknown'}"
            )
        time.sleep(2)
    raise RuntimeError(
        "Canary timed out before the real worker/browser path reached an intentional dry-run or human boundary: "
        + json.dumps(last, sort_keys=True)[:1600]
    )


def run_canary(*, requested_user_id: int | None, timeout_seconds: int) -> dict[str, Any]:
    settings = get_settings()
    revision = current_revision()
    if revision == "unknown":
        raise RuntimeError("Runtime revision is unknown")
    if settings.allow_real_application_submit is not False:
        raise RuntimeError("Real application submission must remain disabled")
    if settings.allow_real_followup_send is not False:
        raise RuntimeError("Recruiter/follow-up sending must remain disabled")

    runtime = runtime_acceptance_status()
    if not runtime.get("ok"):
        raise RuntimeError(
            "Physical Android runtime acceptance is not current: "
            + ",".join(runtime.get("blockers") or [])
        )
    fingerprint = runtime_fingerprint()

    db = SessionLocal()
    session: ShadowRunSession | None = None
    user: User | None = None
    try:
        user = _user(db, requested_user_id)
        # Two slots are required before the canary: one for the canary and at least
        # one for the real timed campaign. Post-canary readiness is checked again.
        pre_policy = campaign_policy_readiness(
            db,
            user,
            requested_duration_seconds=4 * 60 * 60,
            required_remaining_applications=2,
        )
        if not pre_policy.get("ok"):
            raise RuntimeError(
                "Canary admission policy is not ready: "
                + ",".join(pre_policy.get("blockers") or [])
            )

        search_plan = build_search_plan(user)
        if not search_plan.get("ready"):
            raise RuntimeError(
                f"Real discovery plan is unavailable: {search_plan.get('reason_code')}"
            )
        qualification_search_params = _qualification_discovery_search_params(
            search_plan,
            pre_policy,
        )

        session = _create_canary_session(db, user, revision)
        discovery_task = run_job_search.apply_async(
            kwargs={
                "user_id": int(user.id),
                "search_params": {
                    **qualification_search_params,
                    "_origin": "scheduler",
                    "_shadow_session_id": int(session.id),
                    "_qualification_probe": True,
                },
            },
            queue="scraping",
        )
        try:
            discovery = discovery_task.get(timeout=120, propagate=True)
        finally:
            try:
                discovery_task.forget()
            except Exception:
                pass
        if not isinstance(discovery, dict) or int(discovery.get("total_found") or 0) <= 0:
            raise RuntimeError(
                "Real ATS qualification discovery produced no candidates: "
                + json.dumps(discovery, sort_keys=True)[:1200]
            )
        if int(discovery.get("shadow_session_id") or 0) != int(session.id):
            raise RuntimeError("Real discovery lost shadow-session correlation")
        discovery_job_ids = _discovery_job_ids(discovery)
        if not discovery_job_ids:
            raise RuntimeError(
                "Real ATS discovery produced no persisted qualification cohort; "
                "no scheduler application can be attributed to this discovery"
            )

        db.expire_all()
        user = db.query(User).filter(User.id == int(user.id), User.is_active == True).first()
        if user is None:
            raise RuntimeError("Canary user disappeared after discovery")
        scheduler_result = _run_scheduler_cycle_for_user(
            db,
            _apply_only_scheduler_user(
                user,
                qualification_candidate_job_ids=discovery_job_ids,
            ),
            shadow_session_id=int(session.id),
            shadow_application_limit=1,
        )
        if scheduler_result.get("searched") is not False:
            raise RuntimeError(
                "Qualification scheduler launched duplicate discovery after the blocking canary search"
            )
        application_ids = [int(value) for value in scheduler_result.get("application_ids_queued") or []]
        if scheduler_result.get("real_submission_enabled") is not False or scheduler_result.get("dry_run") is not True:
            raise RuntimeError("Scheduler violated canary no-submit invariants")
        if int(scheduler_result.get("shadow_session_id") or 0) != int(session.id):
            raise RuntimeError("Scheduler lost canary shadow-session correlation")
        if len(application_ids) != 1:
            raise RuntimeError(
                "Qualification canary requires exactly one real Application from the production scheduler; "
                f"queued={application_ids} reason={scheduler_result.get('reason')} "
                f"blocked={scheduler_result.get('blocked_job_reasons')}"
            )

        queued_application = _application_snapshot(db, application_ids[0])
        queued_job_id = int(queued_application.get("job_id") or 0)
        if queued_job_id not in set(discovery_job_ids):
            raise RuntimeError(
                "Qualification scheduler selected an Application outside the exact discovery cohort"
            )

        application = _wait_for_application_path(
            db,
            application_ids[0],
            int(session.id),
            timeout_seconds,
        )
        if int(application.get("job_id") or 0) not in set(discovery_job_ids):
            raise RuntimeError(
                "Qualification application lost exact discovery-cohort binding during worker execution"
            )

        db.expire_all()
        user = db.query(User).filter(User.id == int(user.id), User.is_active == True).first()
        if user is None:
            raise RuntimeError("Canary user disappeared before post-canary policy check")
        post_policy = campaign_policy_readiness(
            db,
            user,
            requested_duration_seconds=4 * 60 * 60,
            required_remaining_applications=1,
        )
        if not post_policy.get("ok"):
            raise RuntimeError(
                "Application path worked but campaign capacity/window is no longer available after canary: "
                + ",".join(post_policy.get("blockers") or [])
            )

        report = {
            "version": 1,
            "status": "pass",
            "type": CANARY_TARGET,
            "user_id": int(user.id),
            "session_id": int(session.id),
            "revision": revision,
            "runtime_fingerprint_sha256": fingerprint["sha256"],
            "application_path_observed": True,
            "certification_eligible": False,
            "qualification_discovery_mode": "explicit_public_ats_probe",
            "qualification_discovery_search_params": qualification_search_params,
            "discovery": discovery,
            "discovery_job_ids": discovery_job_ids,
            "discovery_reused_by_scheduler": True,
            "scheduler_application_bound_to_discovery": True,
            "scheduler_result": scheduler_result,
            "application": application,
            "pre_canary_policy": pre_policy,
            "post_canary_policy": post_policy,
            "safety": {
                "real_submission_disabled": True,
                "final_submit_allowed": False,
                "outreach_authorized": False,
                "adapter_maturity_mutated": False,
                "consequential_state_observed": False,
            },
        }
        _finish_canary_session(db, int(session.id), status="completed", report=report)
        receipt = write_receipt(canary_receipt_path(int(user.id)), report)
        return receipt
    except Exception as exc:
        db.rollback()
        failure = {
            "version": 1,
            "status": "fail",
            "type": CANARY_TARGET,
            "user_id": int(user.id) if user is not None else requested_user_id,
            "session_id": int(session.id) if session is not None else None,
            "revision": revision,
            "runtime_fingerprint_sha256": fingerprint["sha256"],
            "application_path_observed": False,
            "certification_eligible": False,
            "failure_reason": str(exc)[:1800],
            "safety": {
                "real_submission_disabled": get_settings().allow_real_application_submit is False,
                "final_submit_allowed": False,
                "outreach_authorized": False,
                "adapter_maturity_mutated": False,
            },
        }
        if session is not None:
            try:
                _finish_canary_session(db, int(session.id), status="failed", report=failure)
            except Exception:
                db.rollback()
        if user is not None:
            write_receipt(canary_receipt_path(int(user.id)), failure)
        raise RuntimeError(str(exc)) from exc
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=CANARY_TIMEOUT_SECONDS)
    args = parser.parse_args()
    try:
        receipt = run_canary(
            requested_user_id=args.user_id,
            timeout_seconds=max(60, int(args.timeout_seconds)),
        )
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
        print(
            "SHADOW_QUALIFICATION_CANARY=PASS "
            f"user_id={receipt['user_id']} application_id={receipt['application']['application_id']} "
            f"revision={receipt['revision']}"
        )
        return 0
    except Exception as exc:
        print(f"SHADOW_QUALIFICATION_CANARY=FAIL reason={str(exc)[:1800]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
