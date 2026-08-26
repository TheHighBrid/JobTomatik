"""Bounded failure-injection drills for the Day 37 eight-hour shadow campaign.

The drills exercise existing production recovery contracts without creating real
submissions, contacting recruiters, changing adapter maturity, or intentionally
failing a shadow scheduler cycle. Each incident is attempted at most once and its
result is retained in the owning ShadowRunCycle observability snapshot.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.services.answer_policy import resolve_runtime_policy, review_reason_for_question
from app.services.browser_runtime import (
    controlled_page_target_id,
    launch_application_browser,
    release_application_browser,
)
from app.services.certification_scale import ensure_aware
from app.services.discovery_search import fold_discovery_results
from app.services.listing_availability import detect_closed_listing
from app.services.operations_policy import evaluate_circuit_breaker_policy


DAY37_INCIDENT_VERSION = "day37-eight-hour-incidents-v1"
DAY37_TARGET = "shadow_run_8h"

# Leave generous recovery time after the final injection. With the canonical 15-minute
# cadence, each threshold lands cleanly on a normal cycle while still tolerating drift.
DAY37_INCIDENT_PLAN: tuple[dict[str, Any], ...] = (
    {
        "incident_type": "source_outage",
        "minimum_elapsed_seconds": 60 * 60,
        "recovery_contract": "independent_source_failure_isolated",
    },
    {
        "incident_type": "browser_crash",
        "minimum_elapsed_seconds": 3 * 60 * 60,
        "recovery_contract": "controlled_page_reacquired_without_browser_process_termination",
    },
    {
        "incident_type": "stale_posting",
        "minimum_elapsed_seconds": 5 * 60 * 60,
        "recovery_contract": "listing_closed_terminal_no_retry",
    },
    {
        "incident_type": "ambiguous_question",
        "minimum_elapsed_seconds": 6 * 60 * 60 + 30 * 60,
        "recovery_contract": "manual_review_required_without_guessing",
    },
)


class Day37InjectedSourceOutage(RuntimeError):
    """Bounded synthetic exception used only by the Day 37 reducer drill."""


def day37_incident_plan() -> list[dict[str, Any]]:
    return [dict(item) for item in DAY37_INCIDENT_PLAN]


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _elapsed_seconds(session: ShadowRunSession, now: datetime) -> float:
    started = ensure_aware(session.started_at) or now
    return max(0.0, (now - started).total_seconds())


def day37_incident_timeline(db, *, session_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == int(session_id))
        .order_by(ShadowRunCycle.cycle_number.asc(), ShadowRunCycle.id.asc())
        .all()
    )
    timeline: list[dict[str, Any]] = []
    for cycle in rows:
        incident = dict((cycle.observability_snapshot or {}).get("day37_incident") or {})
        if not incident:
            continue
        timeline.append(
            {
                **incident,
                "cycle_id": int(cycle.id),
                "cycle_number": int(cycle.cycle_number or 0),
            }
        )
    return timeline


def next_due_day37_incident(
    db,
    session: ShadowRunSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if str(session.target_evidence_type or "") != DAY37_TARGET:
        return None

    current = ensure_aware(now) or datetime.now(timezone.utc)
    elapsed = _elapsed_seconds(session, current)
    attempted = {
        str(item.get("incident_type") or "")
        for item in day37_incident_timeline(db, session_id=int(session.id))
    }
    for planned in DAY37_INCIDENT_PLAN:
        incident_type = str(planned["incident_type"])
        if incident_type in attempted:
            continue
        if elapsed >= float(planned["minimum_elapsed_seconds"]):
            return dict(planned)
    return None


def _source_outage_drill() -> dict[str, Any]:
    recovery_job = {
        "external_id": "day37-recovery-result",
        "source": "lever",
        "url": "https://jobs.lever.co/day37-recovery/example",
        "title": "Controlled recovery result",
        "company": "Day 37 Fixture",
        "raw_data": {},
    }
    folded = fold_discovery_results(
        [
            {"source": "day37-outage", "kind": "broad_board", "target": None},
            {"source": "lever", "kind": "public_ats", "target": "day37-recovery"},
        ],
        [
            Day37InjectedSourceOutage("controlled outage; raw detail must not be retained"),
            [recovery_job],
        ],
        limit=10,
    )
    diagnostics = list(folded.get("source_diagnostics") or [])
    failed = [item for item in diagnostics if item.get("status") == "failed"]
    successful = [item for item in diagnostics if item.get("status") == "success"]
    jobs = list(folded.get("jobs") or [])
    passed = (
        len(failed) == 1
        and failed[0].get("source") == "day37-outage"
        and failed[0].get("error_code") == "day37injectedsourceoutage"
        and len(successful) == 1
        and successful[0].get("source") == "lever"
        and len(jobs) == 1
        and jobs[0].get("external_id") == "day37-recovery-result"
    )
    return {
        "passed": passed,
        "observed": {
            "failed_source_count": len(failed),
            "successful_source_count": len(successful),
            "surviving_result_count": len(jobs),
            "failed_error_code": failed[0].get("error_code") if failed else None,
            "raw_exception_retained": any(
                "controlled outage" in str(value).lower()
                for item in diagnostics
                for value in item.values()
            ),
        },
    }


async def _browser_crash_drill_async() -> dict[str, Any]:
    """Destroy one JobTomatik-owned page and prove a fresh controlled page is usable."""

    from playwright.async_api import async_playwright

    first = None
    second = None
    first_target = ""
    second_target = ""
    destroyed = False
    recovered = False
    try:
        async with async_playwright() as playwright:
            first = await launch_application_browser(playwright)
            first_target = await controlled_page_target_id(first.page)
            await first.page.set_content(
                "<html><head><title>Day37 controlled page</title></head><body>before loss</body></html>"
            )
            await first.page.close(run_before_unload=False)
            destroyed = bool(first.page.is_closed())
            await release_application_browser(first)
            first = None

            second = await launch_application_browser(playwright)
            second_target = await controlled_page_target_id(second.page)
            await second.page.set_content(
                "<html><head><title>Day37 recovered page</title></head><body>recovered</body></html>"
            )
            title = await second.page.title()
            recovered = not bool(second.page.is_closed()) and title == "Day37 recovered page"
            await release_application_browser(second)
            second = None
    except Exception as exc:
        return {
            "passed": False,
            "error_code": type(exc).__name__.lower(),
            "observed": {
                "controlled_page_destroyed": destroyed,
                "fresh_controlled_page_recovered": recovered,
                "browser_process_kill_requested": False,
            },
        }
    finally:
        if first is not None:
            try:
                await release_application_browser(first)
            except Exception:
                pass
        if second is not None:
            try:
                await release_application_browser(second)
            except Exception:
                pass

    return {
        "passed": bool(destroyed and recovered and first_target and second_target and first_target != second_target),
        "observed": {
            "controlled_page_destroyed": destroyed,
            "fresh_controlled_page_recovered": recovered,
            "first_target_present": bool(first_target),
            "second_target_present": bool(second_target),
            "fresh_target_identity": bool(first_target and second_target and first_target != second_target),
            "browser_process_kill_requested": False,
        },
    }


async def _stale_posting_drill_async() -> dict[str, Any]:
    from playwright.async_api import async_playwright

    runtime = None
    try:
        async with async_playwright() as playwright:
            runtime = await launch_application_browser(playwright)
            await runtime.page.set_content(
                """
                <html><head><title>Day 37 stale posting</title></head>
                <body><div role="alert">This job is no longer accepting applications.</div></body>
                </html>
                """
            )
            detected = await detect_closed_listing(runtime.page)
            await release_application_browser(runtime)
            runtime = None
    except Exception as exc:
        return {
            "passed": False,
            "error_code": type(exc).__name__.lower(),
            "observed": {"reason_code": None, "terminal": None, "retryable": None},
        }
    finally:
        if runtime is not None:
            try:
                await release_application_browser(runtime)
            except Exception:
                pass

    detected = dict(detected or {})
    return {
        "passed": (
            detected.get("reason_code") == "listing_closed"
            and detected.get("terminal") is True
            and detected.get("retryable") is False
        ),
        "observed": {
            "reason_code": detected.get("reason_code"),
            "terminal": detected.get("terminal"),
            "retryable": detected.get("retryable"),
            "matched_text_present": bool(detected.get("matched_text")),
        },
    }


def _ambiguous_question_drill() -> dict[str, Any]:
    question = "Provide the internal constellation code for this application."
    resolution = resolve_runtime_policy(question, [])
    review_reason = review_reason_for_question(resolution)
    return {
        "passed": (
            resolution.get("canonical_key") == "custom.unclassified"
            and resolution.get("matched") is False
            and resolution.get("can_autofill") is False
            and resolution.get("answer") in {None, ""}
            and review_reason == "ambiguous_question"
        ),
        "observed": {
            "canonical_key": resolution.get("canonical_key"),
            "matched": resolution.get("matched"),
            "can_autofill": resolution.get("can_autofill"),
            "answer_generated": resolution.get("answer") not in {None, ""},
            "review_reason": review_reason,
        },
    }


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("Day 37 synchronous incident runner cannot execute inside an active event loop")


def _run_incident(incident_type: str) -> dict[str, Any]:
    if incident_type == "source_outage":
        return _source_outage_drill()
    if incident_type == "browser_crash":
        return _run_async(_browser_crash_drill_async())
    if incident_type == "stale_posting":
        return _run_async(_stale_posting_drill_async())
    if incident_type == "ambiguous_question":
        return _ambiguous_question_drill()
    return {"passed": False, "error_code": "unsupported_incident_type", "observed": {}}


def run_due_day37_incident(
    db,
    session: ShadowRunSession,
    *,
    now: datetime | None = None,
    runner: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Attempt at most one due incident and return bounded retained evidence."""

    current = ensure_aware(now) or datetime.now(timezone.utc)
    planned = next_due_day37_incident(db, session, now=current)
    if planned is None:
        return None

    incident_type = str(planned["incident_type"])
    execute = runner or _run_incident
    try:
        result = dict(execute(incident_type) or {})
    except Exception as exc:
        result = {
            "passed": False,
            "error_code": type(exc).__name__.lower(),
            "observed": {},
        }

    breaker = evaluate_circuit_breaker_policy(db, int(session.user_id))
    return {
        "version": DAY37_INCIDENT_VERSION,
        "incident_type": incident_type,
        "planned_minimum_elapsed_seconds": int(planned["minimum_elapsed_seconds"]),
        "observed_elapsed_seconds": _elapsed_seconds(session, current),
        "injected_at": current.replace(microsecond=0).isoformat(),
        "status": "passed" if result.get("passed") is True else "failed",
        "recovery_contract": str(planned["recovery_contract"]),
        "observed": dict(result.get("observed") or {}),
        "error_code": result.get("error_code"),
        "breaker_state": breaker.to_dict(),
        "safety": {
            "real_submission_requested": False,
            "outreach_requested": False,
            "adapter_maturity_mutated": False,
            "browser_process_kill_requested": bool(
                (result.get("observed") or {}).get("browser_process_kill_requested")
            ),
        },
    }


__all__ = [
    "DAY37_INCIDENT_PLAN",
    "DAY37_INCIDENT_VERSION",
    "DAY37_TARGET",
    "day37_incident_plan",
    "day37_incident_timeline",
    "next_due_day37_incident",
    "run_due_day37_incident",
]
