"""Day 37 certifier for a genuinely elapsed eight-hour unattended shadow run.

The certifier reads durable Phase 11 campaign evidence and the four retained Day 37
incident drills. It never advances time, injects incidents, starts a campaign, changes
runtime controls, promotes adapter maturity, or grants submission/outreach authority.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.application import ManualReviewStatus, ManualReviewTask
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.services.certification_scale import canonical_hash, current_revision, ensure_aware
from app.services.day36_shadow_endurance import (
    _browser_cleanup_report,
    _cycle_coverage,
    _iso,
    _lever_manifest_state,
    _load_frozen_configuration,
    _notification_quality,
    _seconds_between,
    _verify_retained_report,
)
from app.services.day37_shadow_admission import day37_predecessor_admission
from app.services.day37_shadow_incidents import (
    DAY37_INCIDENT_PLAN,
    DAY37_INCIDENT_VERSION,
    day37_incident_timeline,
)
from app.services.operations_policy import evaluate_circuit_breaker_policy


DAY37_ENDURANCE_VERSION = "day37-eight-hour-shadow-v1"
DAY37_TARGET = "shadow_run_8h"
DAY37_SECONDS = 8 * 60 * 60


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _aware(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_aware(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return ensure_aware(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _incident_report(db, session: ShadowRunSession) -> dict[str, Any]:
    timeline = day37_incident_timeline(db, session_id=int(session.id))
    expected_types = [str(item["incident_type"]) for item in DAY37_INCIDENT_PLAN]
    observed_types = [str(item.get("incident_type") or "") for item in timeline]
    counts = {name: observed_types.count(name) for name in expected_types}
    plan_by_type = {str(item["incident_type"]): dict(item) for item in DAY37_INCIDENT_PLAN}

    session_start = _aware(session.started_at)
    session_end = _aware(session.completed_at)
    threshold_failures: list[str] = []
    outside_session: list[str] = []
    recovery_contract_mismatches: list[str] = []
    invalid_safety: list[str] = []
    failed_incidents: list[str] = []
    invalid_breaker_states: list[str] = []

    for item in timeline:
        incident_type = str(item.get("incident_type") or "")
        planned = plan_by_type.get(incident_type) or {}
        if item.get("status") != "passed":
            failed_incidents.append(incident_type or "unknown")
        if str(item.get("version") or "") != DAY37_INCIDENT_VERSION:
            failed_incidents.append(f"{incident_type}:version")

        planned_threshold = int(planned.get("minimum_elapsed_seconds") or 0)
        observed_elapsed = float(item.get("observed_elapsed_seconds") or 0.0)
        if observed_elapsed < planned_threshold:
            threshold_failures.append(incident_type)

        injected_at = _aware(item.get("injected_at"))
        if (
            injected_at is None
            or session_start is None
            or session_end is None
            or injected_at < session_start
            or injected_at > session_end
        ):
            outside_session.append(incident_type)

        if str(item.get("recovery_contract") or "") != str(planned.get("recovery_contract") or ""):
            recovery_contract_mismatches.append(incident_type)

        safety = dict(item.get("safety") or {})
        if (
            safety.get("real_submission_requested") is not False
            or safety.get("outreach_requested") is not False
            or safety.get("adapter_maturity_mutated") is not False
            or safety.get("browser_process_kill_requested") is not False
        ):
            invalid_safety.append(incident_type)

        breaker = dict(item.get("breaker_state") or {})
        if breaker.get("allowed") is not True or breaker.get("code") != "circuit_breaker_closed":
            invalid_breaker_states.append(incident_type)

    specialized = {item.get("incident_type"): dict(item.get("observed") or {}) for item in timeline}
    source = specialized.get("source_outage") or {}
    browser = specialized.get("browser_crash") or {}
    stale = specialized.get("stale_posting") or {}
    ambiguous = specialized.get("ambiguous_question") or {}

    checks = {
        "all_four_incidents_present_exactly_once": len(timeline) == len(expected_types)
        and all(counts.get(name) == 1 for name in expected_types),
        "incident_order_matches_plan": observed_types == expected_types,
        "all_incidents_passed": not failed_incidents,
        "incident_thresholds_respected": not threshold_failures,
        "incidents_within_session_window": not outside_session,
        "recovery_contracts_match_plan": not recovery_contract_mismatches,
        "incident_safety_preserved": not invalid_safety,
        "isolated_incidents_did_not_trip_cluster_breaker": not invalid_breaker_states,
        "source_outage_isolated_without_raw_exception": (
            int(source.get("failed_source_count") or 0) == 1
            and int(source.get("successful_source_count") or 0) == 1
            and int(source.get("surviving_result_count") or 0) == 1
            and source.get("raw_exception_retained") is False
        ),
        "browser_controlled_page_recovered": (
            browser.get("controlled_page_destroyed") is True
            and browser.get("fresh_controlled_page_recovered") is True
            and browser.get("fresh_target_identity") is True
            and browser.get("browser_process_kill_requested") is False
        ),
        "stale_posting_terminal_without_retry": (
            stale.get("reason_code") == "listing_closed"
            and stale.get("terminal") is True
            and stale.get("retryable") is False
        ),
        "ambiguous_question_handed_off_without_guessing": (
            ambiguous.get("canonical_key") == "custom.unclassified"
            and ambiguous.get("can_autofill") is False
            and ambiguous.get("answer_generated") is False
            and ambiguous.get("review_reason") == "ambiguous_question"
        ),
    }
    return {
        "version": DAY37_INCIDENT_VERSION,
        "plan": [dict(item) for item in DAY37_INCIDENT_PLAN],
        "timeline": timeline,
        "observed_types": observed_types,
        "counts": counts,
        "failed_incidents": failed_incidents,
        "threshold_failures": threshold_failures,
        "outside_session": outside_session,
        "recovery_contract_mismatches": recovery_contract_mismatches,
        "invalid_safety": invalid_safety,
        "invalid_breaker_states": invalid_breaker_states,
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_day37_shadow_endurance_report(
    db,
    *,
    session_id: int,
    user_id: int | None = None,
    expected_revision: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Certify one retained eight-hour session without synthesizing elapsed time."""

    query = db.query(ShadowRunSession).filter(ShadowRunSession.id == int(session_id))
    if user_id is not None:
        query = query.filter(ShadowRunSession.user_id == int(user_id))
    session = query.first()
    if session is None:
        raise ValueError("Shadow session not found")

    repo_root = root or _root()
    frozen, frozen_sha256 = _load_frozen_configuration(repo_root)
    frozen_candidate = dict(frozen.get("candidate") or {})
    frozen_simulation = dict(frozen.get("simulation") or {})
    lever = _lever_manifest_state()
    revision = str(expected_revision or current_revision())

    retained = _verify_retained_report(session)
    final_report = dict(retained.get("report") or {})
    reconciliation = dict(final_report.get("reconciliation") or {})
    safety = dict(final_report.get("safety") or {})
    quality = dict(final_report.get("quality") or {})

    persisted_elapsed = _seconds_between(session.started_at, session.completed_at)
    report_elapsed = _seconds_between(final_report.get("started_at"), final_report.get("completed_at"))
    try:
        measured = float(final_report.get("measured_duration_seconds") or 0.0)
    except (TypeError, ValueError):
        measured = 0.0

    cycles = (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == session.id)
        .order_by(ShadowRunCycle.cycle_number.asc(), ShadowRunCycle.id.asc())
        .all()
    )
    coverage = _cycle_coverage(cycles, session)
    application_ids = [int(item) for item in reconciliation.get("unique_application_ids") or []]
    browser_cleanup = _browser_cleanup_report(db, session=session, application_ids=application_ids)
    notifications = _notification_quality(db, session=session, application_ids=application_ids)
    incidents = _incident_report(db, session)
    predecessor = day37_predecessor_admission(
        db,
        user_id=int(session.user_id),
        root=repo_root,
    )
    breaker = evaluate_circuit_breaker_policy(db, int(session.user_id)).to_dict()

    duration_hours = persisted_elapsed / 3600.0 if persisted_elapsed else 0.0
    cycles_total = max(1, int(coverage["cycle_count"]))
    throughput = {
        "measured_hours": round(duration_hours, 4),
        "cycles_per_hour": round(int(coverage["completed_cycle_count"]) / duration_hours, 4)
        if duration_hours > 0
        else 0.0,
        "applications_created": len(application_ids),
        "applications_per_hour": round(len(application_ids) / duration_hours, 4)
        if duration_hours > 0
        else 0.0,
        "discovery_total_found": int((reconciliation.get("discovery") or {}).get("total_found") or 0),
        "discovery_saved": int((reconciliation.get("discovery") or {}).get("saved") or 0),
        "cycle_error_rate": round(int(coverage["failed_cycle_count"]) / cycles_total, 6),
    }

    reviews = (
        db.query(ManualReviewTask)
        .filter(ManualReviewTask.application_id.in_(application_ids))
        .all()
        if application_ids
        else []
    )
    open_reviews = [
        int(item.id)
        for item in reviews
        if str(item.status or "") in {ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value}
    ]

    memory_samples = list((coverage.get("memory") or {}).get("samples") or [])
    memory_pids = {
        int(sample["pid"])
        for sample in memory_samples
        if sample.get("pid") not in (None, "")
    }

    checks = {
        "session_completed": session.status == "completed",
        "target_is_exact_8h": session.target_evidence_type == DAY37_TARGET
        and int(session.requested_duration_seconds or 0) == DAY37_SECONDS,
        "persisted_elapsed_at_least_8h": persisted_elapsed is not None and persisted_elapsed >= DAY37_SECONDS,
        "retained_report_elapsed_at_least_8h": measured >= DAY37_SECONDS
        and report_elapsed is not None
        and report_elapsed >= DAY37_SECONDS,
        "persisted_and_report_timestamps_match": (
            _iso(session.started_at) == _iso(final_report.get("started_at"))
            and _iso(session.completed_at) == _iso(final_report.get("completed_at"))
        ),
        "retained_report_hash_valid": bool(retained["valid"]),
        "retained_report_qualification_eligible": final_report.get("qualification_eligible") is True,
        "candidate_revision_matches_exact_runtime": str(session.candidate_revision) == revision,
        "continuous_cycle_coverage": bool(coverage["continuous_cycle_coverage"]),
        "memory_telemetry_present": bool(coverage["memory"]["telemetry_present"]),
        "worker_process_identity_stable": len(memory_pids) == 1,
        "zero_cycle_failures": int(coverage["failed_cycle_count"]) == 0,
        "zero_duplicate_tasks": (
            not coverage["duplicate_cycle_numbers"]
            and not coverage["overlapping_cycles"]
            and int(reconciliation.get("duplicate_application_references") or 0) == 0
        ),
        "zero_false_status": not bool(reconciliation.get("submitted_application_ids")),
        "zero_runaway_retry": not bool(reconciliation.get("runaway_retry_application_ids")),
        "zero_unexplained_records": int(reconciliation.get("unexplained_records") or 0) == 0,
        "zero_policy_escape": not bool(reconciliation.get("policy_escapes")),
        "no_active_application_work": not bool(reconciliation.get("active_application_ids")),
        "browser_cleanup_reconciled": bool(browser_cleanup["cleanup_reconciled"]),
        "notification_quality_ok": bool(notifications["quality_ok"]),
        "all_day37_incident_recovery_gates_passed": bool(incidents["passed"]),
        "verified_day36_predecessor_still_valid": bool(predecessor.get("ok")),
        "cluster_breaker_clear_at_certification": breaker.get("allowed") is True
        and breaker.get("code") == "circuit_breaker_closed",
        "final_submit_disabled": safety.get("final_submit_enabled") is False
        and safety.get("final_submit_clicked") is False
        and safety.get("real_submission_remained_disabled") is True,
        "frozen_candidate_is_lever_1_1_0_dry_run": (
            frozen_candidate.get("adapter") == "lever"
            and frozen_candidate.get("adapter_version") == "1.1.0"
            and frozen_candidate.get("required_current_maturity") == "dry_run"
            and frozen_candidate.get("promotion_authorized") is False
            and frozen_simulation.get("final_submit_allowed") is False
        ),
        "live_manifest_still_matches_frozen_candidate": (
            lever.get("name") == "lever"
            and lever.get("version") == "1.1.0"
            and lever.get("maturity") == "dry_run"
            and lever.get("autonomous_submission_allowed") is False
        ),
    }
    checks["phase11_quality_gate_passed"] = bool(quality) and all(bool(value) for value in quality.values())

    report: dict[str, Any] = {
        "version": DAY37_ENDURANCE_VERSION,
        "session_id": int(session.id),
        "user_id": int(session.user_id),
        "candidate_revision": str(session.candidate_revision),
        "verification_revision": revision,
        "target_evidence_type": str(session.target_evidence_type),
        "requested_duration_seconds": int(session.requested_duration_seconds or 0),
        "persisted_elapsed_seconds": persisted_elapsed,
        "retained_measured_duration_seconds": measured,
        "started_at": _iso(session.started_at),
        "completed_at": _iso(session.completed_at),
        "day35_configuration_sha256": frozen_sha256,
        "frozen_candidate": frozen_candidate,
        "live_candidate_manifest": lever,
        "throughput": throughput,
        "memory": {
            **dict(coverage["memory"]),
            "distinct_worker_pids": sorted(memory_pids),
        },
        "cycle_coverage": {key: value for key, value in coverage.items() if key != "memory"},
        "browser_cleanup": browser_cleanup,
        "notification_quality": notifications,
        "manual_review": {
            "count": len(reviews),
            "open_or_in_progress_review_ids": open_reviews,
        },
        "incidents": incidents,
        "predecessor": predecessor,
        "breaker_at_certification": breaker,
        "retained_phase11_report_sha256": retained.get("claimed_sha256"),
        "checks": checks,
        "safety": {
            "final_submit_clicked": bool(safety.get("final_submit_clicked")),
            "real_submission_remained_disabled": safety.get("real_submission_remained_disabled") is True,
            "submission_authorized": False,
            "outreach_authorized": False,
            "adapter_maturity_mutated": False,
            "promotion_authorized": False,
        },
    }
    report["passed"] = all(checks.values())
    report["day38_entry_eligible"] = report["passed"]
    report["report_sha256"] = canonical_hash(report)
    return report


__all__ = [
    "DAY37_ENDURANCE_VERSION",
    "DAY37_SECONDS",
    "DAY37_TARGET",
    "build_day37_shadow_endurance_report",
]
