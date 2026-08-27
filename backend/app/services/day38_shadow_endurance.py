"""Strict post-run certifier for the Day 38 twenty-four-hour shadow campaign.

The certifier consumes retained Phase 11 evidence. It never starts, advances, repairs,
or reviews a campaign and never changes adapter maturity or submission/outreach flags.
Day 38 additionally requires diagnostic production-policy telemetry proving that a full
24-hour no-submit run crossed configured quiet hours and the rolling 24-hour capacity
threshold while execution itself remained on the non-authoritative ``shadow_test``
profile.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.application import ManualReviewStatus, ManualReviewTask
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.services.certification_scale import canonical_hash, current_revision
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
from app.services.day38_runtime import (
    DAY38_POLICY_SNAPSHOT_KEY,
    DAY38_POLICY_TELEMETRY_VERSION,
)
from app.services.day38_shadow_admission import (
    DAY38_SECONDS,
    DAY38_TARGET,
    day38_predecessor_admission,
)
from app.services.operations_policy import evaluate_circuit_breaker_policy


DAY38_ENDURANCE_VERSION = "day38-twenty-four-hour-shadow-v1"


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _policy_transition_report(cycles: list[ShadowRunCycle]) -> dict[str, Any]:
    completed = [cycle for cycle in cycles if str(cycle.status or "") == "completed"]
    samples: list[dict[str, Any]] = []
    missing_cycle_numbers: list[int] = []
    wrong_versions: list[int] = []
    authoritative_cycle_numbers: list[int] = []
    execution_profile_mismatches: list[int] = []
    unsafe_cycle_numbers: list[int] = []

    for cycle in completed:
        snapshot = dict(cycle.reconciliation_snapshot or {})
        diagnostic = snapshot.get(DAY38_POLICY_SNAPSHOT_KEY)
        if not isinstance(diagnostic, dict):
            missing_cycle_numbers.append(int(cycle.cycle_number))
            continue
        item = dict(diagnostic)
        item["cycle_number"] = int(cycle.cycle_number)
        samples.append(item)
        if str(item.get("version") or "") != DAY38_POLICY_TELEMETRY_VERSION:
            wrong_versions.append(int(cycle.cycle_number))
        if item.get("authoritative") is not False:
            authoritative_cycle_numbers.append(int(cycle.cycle_number))

        scheduler = dict(cycle.scheduler_result or {})
        if str(scheduler.get("policy_profile") or "") != "shadow_test":
            execution_profile_mismatches.append(int(cycle.cycle_number))
        if scheduler.get("production_limits_enforced") is not False:
            execution_profile_mismatches.append(int(cycle.cycle_number))

        safety = dict(item.get("safety") or {})
        if (
            safety.get("used_to_authorize_shadow_execution") is not False
            or safety.get("used_to_block_shadow_execution") is not False
            or safety.get("submission_authorized") is not False
            or safety.get("outreach_authorized") is not False
        ):
            unsafe_cycle_numbers.append(int(cycle.cycle_number))

    quiet_pairs = {
        (
            int((sample.get("quiet_hours") or {}).get("start_hour_utc") or 0),
            int((sample.get("quiet_hours") or {}).get("end_hour_utc") or 0),
        )
        for sample in samples
    }
    quiet_configured = any(
        bool((sample.get("quiet_hours") or {}).get("configured")) for sample in samples
    )
    quiet_states = {
        bool((sample.get("quiet_hours") or {}).get("active")) for sample in samples
    }

    daily_caps = {
        int((sample.get("rolling_24h_capacity") or {}).get("cap") or 0)
        for sample in samples
        if int((sample.get("rolling_24h_capacity") or {}).get("cap") or 0) > 0
    }
    daily_counts = [
        int((sample.get("rolling_24h_capacity") or {}).get("count") or 0)
        for sample in samples
    ]
    daily_cap = next(iter(daily_caps)) if len(daily_caps) == 1 else None
    below_cap_observed = bool(
        daily_cap is not None and any(count < daily_cap for count in daily_counts)
    )
    at_or_above_cap_observed = bool(
        daily_cap is not None and any(count >= daily_cap for count in daily_counts)
    )

    decision_codes = [
        str((sample.get("production_decision") or {}).get("code") or "")
        for sample in samples
    ]

    checks = {
        "every_completed_cycle_has_policy_diagnostic": bool(completed)
        and not missing_cycle_numbers
        and len(samples) == len(completed),
        "policy_diagnostic_version_exact": not wrong_versions,
        "production_diagnostic_never_authoritative": not authoritative_cycle_numbers,
        "shadow_execution_profile_remained_shadow_test": not execution_profile_mismatches,
        "policy_diagnostic_never_changed_execution_authority": not unsafe_cycle_numbers,
        "quiet_hours_configuration_stable": len(quiet_pairs) == 1,
        "quiet_hours_transition_observed": (
            True if not quiet_configured else quiet_states == {False, True}
        ),
        "rolling_24h_cap_stable": len(daily_caps) == 1,
        "rolling_24h_capacity_threshold_crossed": below_cap_observed
        and at_or_above_cap_observed,
    }

    return {
        "version": DAY38_POLICY_TELEMETRY_VERSION,
        "sample_count": len(samples),
        "completed_cycle_count": len(completed),
        "missing_cycle_numbers": missing_cycle_numbers,
        "wrong_version_cycle_numbers": wrong_versions,
        "authoritative_cycle_numbers": authoritative_cycle_numbers,
        "execution_profile_mismatch_cycle_numbers": sorted(
            set(execution_profile_mismatches)
        ),
        "unsafe_cycle_numbers": unsafe_cycle_numbers,
        "quiet_hours": {
            "configuration_pairs": sorted(quiet_pairs),
            "configured": quiet_configured,
            "observed_active_states": sorted(quiet_states),
        },
        "rolling_24h_capacity": {
            "caps": sorted(daily_caps),
            "minimum_count": min(daily_counts) if daily_counts else None,
            "maximum_count": max(daily_counts) if daily_counts else None,
            "below_cap_observed": below_cap_observed,
            "at_or_above_cap_observed": at_or_above_cap_observed,
            "semantics": "rolling_previous_24_hours",
        },
        "production_decision_codes": decision_codes,
        "checks": checks,
        "passed": all(checks.values()),
        "samples": samples,
    }


def build_day38_shadow_endurance_report(
    db,
    *,
    session_id: int,
    user_id: int | None = None,
    expected_revision: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Certify one genuinely elapsed 24-hour session without synthesizing time."""

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
    report_elapsed = _seconds_between(
        final_report.get("started_at"), final_report.get("completed_at")
    )
    try:
        measured = float(final_report.get("measured_duration_seconds") or 0.0)
    except (TypeError, ValueError):
        measured = 0.0

    cycles = (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == int(session.id))
        .order_by(ShadowRunCycle.cycle_number.asc(), ShadowRunCycle.id.asc())
        .all()
    )
    coverage = _cycle_coverage(cycles, session)
    policy_transitions = _policy_transition_report(cycles)
    application_ids = [
        int(item) for item in reconciliation.get("unique_application_ids") or []
    ]
    browser_cleanup = _browser_cleanup_report(
        db,
        session=session,
        application_ids=application_ids,
    )
    notifications = _notification_quality(
        db,
        session=session,
        application_ids=application_ids,
    )
    predecessor = day38_predecessor_admission(
        db,
        user_id=int(session.user_id),
        root=repo_root,
    )
    breaker = evaluate_circuit_breaker_policy(db, int(session.user_id)).to_dict()

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
        if str(item.status or "")
        in {ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value}
    ]

    memory_samples = list((coverage.get("memory") or {}).get("samples") or [])
    memory_pids = {
        int(sample["pid"])
        for sample in memory_samples
        if sample.get("pid") not in (None, "")
    }
    settings = get_settings()

    checks = {
        "session_completed": str(session.status or "") == "completed",
        "target_is_exact_24h": str(session.target_evidence_type or "") == DAY38_TARGET
        and int(session.requested_duration_seconds or 0) == DAY38_SECONDS,
        "persisted_elapsed_at_least_24h": persisted_elapsed is not None
        and persisted_elapsed >= DAY38_SECONDS,
        "retained_report_elapsed_at_least_24h": measured >= DAY38_SECONDS
        and report_elapsed is not None
        and report_elapsed >= DAY38_SECONDS,
        "persisted_and_report_timestamps_match": (
            _iso(session.started_at) == _iso(final_report.get("started_at"))
            and _iso(session.completed_at) == _iso(final_report.get("completed_at"))
        ),
        "retained_report_hash_valid": bool(retained["valid"]),
        "retained_report_qualification_eligible": final_report.get(
            "qualification_eligible"
        )
        is True,
        "candidate_revision_matches_exact_runtime": str(session.candidate_revision)
        == revision,
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
        "zero_runaway_retry": not bool(
            reconciliation.get("runaway_retry_application_ids")
        ),
        "zero_unexplained_records": int(
            reconciliation.get("unexplained_records") or 0
        )
        == 0,
        "zero_policy_escape": not bool(reconciliation.get("policy_escapes")),
        "no_active_application_work": not bool(
            reconciliation.get("active_application_ids")
        ),
        "browser_cleanup_reconciled": bool(browser_cleanup["cleanup_reconciled"]),
        "notification_quality_ok": bool(notifications["quality_ok"]),
        "verified_day37_predecessor_still_valid": bool(predecessor.get("ok")),
        "production_policy_transition_evidence_passed": bool(
            policy_transitions["passed"]
        ),
        "cluster_breaker_clear_at_certification": breaker.get("allowed") is True
        and breaker.get("code") == "circuit_breaker_closed",
        "final_submit_disabled": safety.get("final_submit_enabled") is False
        and safety.get("final_submit_clicked") is False
        and safety.get("real_submission_remained_disabled") is True,
        "real_followup_send_still_disabled": settings.allow_real_followup_send is False,
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
    checks["phase11_quality_gate_passed"] = bool(quality) and all(
        bool(value) for value in quality.values()
    )

    duration_hours = persisted_elapsed / 3600.0 if persisted_elapsed else 0.0
    cycles_total = max(1, int(coverage["cycle_count"]))
    report: dict[str, Any] = {
        "version": DAY38_ENDURANCE_VERSION,
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
        "throughput": {
            "measured_hours": round(duration_hours, 4),
            "cycles_per_hour": round(
                int(coverage["completed_cycle_count"]) / duration_hours, 4
            )
            if duration_hours > 0
            else 0.0,
            "applications_created": len(application_ids),
            "applications_per_hour": round(len(application_ids) / duration_hours, 4)
            if duration_hours > 0
            else 0.0,
            "cycle_error_rate": round(
                int(coverage["failed_cycle_count"]) / cycles_total, 6
            ),
        },
        "memory": {
            **dict(coverage["memory"]),
            "distinct_worker_pids": sorted(memory_pids),
        },
        "cycle_coverage": {
            key: value for key, value in coverage.items() if key != "memory"
        },
        "production_policy_transitions": policy_transitions,
        "browser_cleanup": browser_cleanup,
        "notification_quality": notifications,
        "manual_review": {
            "count": len(reviews),
            "open_or_in_progress_review_ids": open_reviews,
        },
        "predecessor": predecessor,
        "breaker_at_certification": breaker,
        "retained_phase11_report_sha256": retained.get("claimed_sha256"),
        "checks": checks,
        "safety": {
            "final_submit_clicked": bool(safety.get("final_submit_clicked")),
            "real_submission_remained_disabled": safety.get(
                "real_submission_remained_disabled"
            )
            is True,
            "real_followup_send_disabled_at_certification": settings.allow_real_followup_send
            is False,
            "submission_authorized": False,
            "outreach_authorized": False,
            "adapter_maturity_mutated": False,
            "promotion_authorized": False,
        },
    }
    report["passed"] = all(checks.values())
    report["day39_entry_eligible"] = report["passed"]
    report["report_sha256"] = canonical_hash(report)
    return report


__all__ = [
    "DAY38_ENDURANCE_VERSION",
    "DAY38_SECONDS",
    "DAY38_TARGET",
    "build_day38_shadow_endurance_report",
]
