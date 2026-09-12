"""Day 36 certifier for a genuinely elapsed four-hour unattended shadow run.

This module reads retained Phase 11 campaign evidence. It never advances time, starts a
campaign, submits an application, promotes adapter maturity, or authorizes outreach.
A passing result requires persisted timestamps and cycle coverage spanning at least
14,400 real seconds plus the frozen Day 35 Lever configuration.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.application import Application, ManualReviewStatus, ManualReviewTask
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.models.handoff import ACTIVE_HANDOFF_STATUSES, ManualHandoffSession
from app.models.notification import Notification, NotificationType
from app.services.ats_manifest import ats_certification_manifest
from app.services.certification_scale import canonical_hash, current_revision, ensure_aware
from app.services.day35_operations_rehearsal import canonical_sha256


DAY36_ENDURANCE_VERSION = "day36-four-hour-shadow-v1"
DAY36_TARGET = "shadow_run_4h"
DAY36_SECONDS = 4 * 60 * 60
DAY35_CONFIGURATION_PATH = "backend/evidence/day35-unattended-pilot-configuration.json"
MAX_CADENCE_GRACE_SECONDS = 30 * 60


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
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ensure_aware(parsed)


def _iso(value: datetime | str | None) -> str | None:
    aware = _aware(value)
    return aware.replace(microsecond=0).isoformat() if aware else None


def _seconds_between(
    left: datetime | str | None,
    right: datetime | str | None,
) -> float | None:
    start = _aware(left)
    end = _aware(right)
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def _load_frozen_configuration(root: Path) -> tuple[dict[str, Any], str]:
    path = root / DAY35_CONFIGURATION_PATH
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Day 35 unattended-pilot configuration must be a JSON object")
    return value, canonical_sha256(value)


def _lever_manifest_state() -> dict[str, Any]:
    manifest = ats_certification_manifest()
    row = next(
        (
            dict(item)
            for item in manifest.get("adapters", [])
            if isinstance(item, dict) and str(item.get("name") or "").lower() == "lever"
        ),
        {},
    )
    return {
        "name": row.get("name"),
        "version": row.get("version") or row.get("adapter_version"),
        "maturity": row.get("maturity"),
        "autonomous_submission_allowed": bool(row.get("autonomous_submission_allowed")),
    }


def _verify_retained_report(session: ShadowRunSession) -> dict[str, Any]:
    stored = dict(session.final_report or {})
    claimed_hash = str(stored.get("report_sha256") or "")
    payload = dict(stored)
    payload.pop("report_sha256", None)
    computed = canonical_hash(payload) if stored else ""
    return {
        "present": bool(stored),
        "claimed_sha256": claimed_hash or None,
        "session_sha256": session.report_sha256,
        "computed_sha256": computed or None,
        "valid": bool(stored)
        and bool(claimed_hash)
        and claimed_hash == computed
        and claimed_hash == str(session.report_sha256 or ""),
        "report": stored,
    }


def _cycle_coverage(cycles: list[ShadowRunCycle], session: ShadowRunSession) -> dict[str, Any]:
    interval = max(60, int(session.cycle_interval_seconds or 0))
    max_gap = max(MAX_CADENCE_GRACE_SECONDS, interval * 2)
    cycle_numbers: list[int] = []
    starts: list[datetime] = []
    overlaps: list[tuple[int, int]] = []
    incomplete: list[int] = []
    memory_samples: list[dict[str, Any]] = []

    previous: ShadowRunCycle | None = None
    for cycle in cycles:
        number = int(cycle.cycle_number or 0)
        cycle_numbers.append(number)
        started = _aware(cycle.started_at)
        completed = _aware(cycle.completed_at)
        if started is not None:
            starts.append(started)
        if cycle.status != "completed" or started is None or completed is None or completed < started:
            incomplete.append(number)
        if previous is not None:
            previous_completed = _aware(previous.completed_at)
            if previous_completed is not None and started is not None and started < previous_completed:
                overlaps.append((int(previous.cycle_number or 0), number))
        previous = cycle

        observability = dict(cycle.observability_snapshot or {})
        memory = observability.get("day36_runtime_memory")
        if isinstance(memory, dict):
            rss = memory.get("rss_kib")
            peak = memory.get("peak_rss_kib")
            if rss is not None or peak is not None:
                memory_samples.append(
                    {
                        "cycle_number": number,
                        "rss_kib": int(rss) if rss is not None else None,
                        "peak_rss_kib": int(peak) if peak is not None else None,
                        "pid": memory.get("pid"),
                        "source": memory.get("source"),
                    }
                )

    duplicate_numbers = sorted(
        number for number, count in Counter(cycle_numbers).items() if count > 1
    )
    gaps = [
        max(0.0, (right - left).total_seconds())
        for left, right in zip(starts, starts[1:])
    ]
    session_start = _aware(session.started_at)
    expected_end = _aware(session.expected_end_at)
    first_delay = (
        max(0.0, (starts[0] - session_start).total_seconds())
        if starts and session_start is not None
        else None
    )
    tail_gap = (
        max(0.0, (expected_end - starts[-1]).total_seconds())
        if starts and expected_end is not None
        else None
    )
    max_observed_gap = max(gaps, default=0.0)

    rss_values = [sample["rss_kib"] for sample in memory_samples if sample["rss_kib"] is not None]
    peak_values = [sample["peak_rss_kib"] for sample in memory_samples if sample["peak_rss_kib"] is not None]
    memory_summary = {
        "sample_count": len(memory_samples),
        "samples": memory_samples,
        "first_rss_kib": rss_values[0] if rss_values else None,
        "last_rss_kib": rss_values[-1] if rss_values else None,
        "min_rss_kib": min(rss_values) if rss_values else None,
        "max_rss_kib": max(rss_values) if rss_values else None,
        "max_peak_rss_kib": max(peak_values) if peak_values else None,
        "rss_growth_kib": rss_values[-1] - rss_values[0] if len(rss_values) >= 2 else None,
        "telemetry_present": len(memory_samples) >= 2,
    }

    cadence_continuous = (
        bool(cycles)
        and not incomplete
        and not duplicate_numbers
        and not overlaps
        and first_delay is not None
        and first_delay <= max_gap
        and tail_gap is not None
        and tail_gap <= max_gap
        and max_observed_gap <= max_gap
    )
    return {
        "cycle_count": len(cycles),
        "completed_cycle_count": sum(1 for item in cycles if item.status == "completed"),
        "failed_cycle_count": sum(1 for item in cycles if item.status == "failed"),
        "cycle_numbers": cycle_numbers,
        "duplicate_cycle_numbers": duplicate_numbers,
        "incomplete_cycle_numbers": incomplete,
        "overlapping_cycles": [list(item) for item in overlaps],
        "configured_interval_seconds": interval,
        "maximum_allowed_gap_seconds": max_gap,
        "first_cycle_delay_seconds": first_delay,
        "maximum_observed_cycle_gap_seconds": max_observed_gap,
        "last_cycle_to_expected_end_seconds": tail_gap,
        "continuous_cycle_coverage": cadence_continuous,
        "memory": memory_summary,
    }


def _browser_cleanup_report(
    db,
    *,
    session: ShadowRunSession,
    application_ids: list[int],
) -> dict[str, Any]:
    if not application_ids:
        return {
            "application_count": 0,
            "retained_browser_application_ids": [],
            "handoff_application_ids": [],
            "active_handoff_application_ids": [],
            "unaccounted_retained_browser_application_ids": [],
            "cleanup_reconciled": False,
        }

    applications = (
        db.query(Application)
        .filter(Application.id.in_(application_ids), Application.user_id == session.user_id)
        .all()
    )
    retained: set[int] = set()
    for application in applications:
        for entry in list(application.automation_log or []):
            if isinstance(entry, dict) and entry.get("action") == "browser_handoff_retained":
                retained.add(int(application.id))

    handoffs = (
        db.query(ManualHandoffSession)
        .filter(
            ManualHandoffSession.user_id == session.user_id,
            ManualHandoffSession.application_id.in_(application_ids),
        )
        .all()
    )
    handoff_ids = {int(item.application_id) for item in handoffs}
    active_ids = {
        int(item.application_id)
        for item in handoffs
        if str(item.status or "") in ACTIVE_HANDOFF_STATUSES
    }
    unaccounted = sorted(retained - handoff_ids)
    return {
        "application_count": len(applications),
        "retained_browser_application_ids": sorted(retained),
        "handoff_application_ids": sorted(handoff_ids),
        "active_handoff_application_ids": sorted(active_ids),
        "unaccounted_retained_browser_application_ids": unaccounted,
        "cleanup_reconciled": not unaccounted,
        "interpretation": (
            "Retained controlled pages are acceptable only when backed by a durable handoff; "
            "all other application browser work is required to release its controlled page."
        ),
    }


def _notification_quality(
    db,
    *,
    session: ShadowRunSession,
    application_ids: list[int],
) -> dict[str, Any]:
    rows = (
        db.query(Notification)
        .filter(
            Notification.user_id == session.user_id,
            Notification.created_at >= session.started_at,
            Notification.created_at <= (session.completed_at or session.expected_end_at),
        )
        .order_by(Notification.created_at.asc(), Notification.id.asc())
        .all()
    )
    app_set = set(application_ids)
    relevant: list[Notification] = []
    for item in rows:
        data = dict(item.data or {})
        try:
            application_id = int(data.get("application_id"))
        except (TypeError, ValueError):
            application_id = None
        try:
            shadow_session_id = int(data.get("shadow_session_id"))
        except (TypeError, ValueError):
            shadow_session_id = None
        if application_id in app_set or shadow_session_id == int(session.id):
            relevant.append(item)

    fingerprints: Counter[tuple[Any, ...]] = Counter()
    routine_noise_ids: list[int] = []
    missing_action_context_ids: list[int] = []
    public_rows: list[dict[str, Any]] = []
    for item in relevant:
        data = dict(item.data or {})
        type_value = item.type.value if hasattr(item.type, "value") else str(item.type)
        fingerprint = (
            type_value,
            str(item.title or ""),
            data.get("application_id"),
            data.get("reason"),
            data.get("handoff_public_id"),
        )
        fingerprints[fingerprint] += 1
        if type_value == NotificationType.new_match.value and str(data.get("origin") or "") == "scheduler":
            routine_noise_ids.append(int(item.id))
        if type_value == NotificationType.system.value and not any(
            data.get(key) not in (None, "")
            for key in ("application_id", "reason", "handoff_public_id", "recovery_path")
        ):
            missing_action_context_ids.append(int(item.id))
        public_rows.append(
            {
                "notification_id": int(item.id),
                "type": type_value,
                "title": str(item.title or "")[:160],
                "application_id": data.get("application_id"),
                "reason": data.get("reason"),
                "has_handoff_reference": bool(data.get("handoff_public_id")),
            }
        )

    duplicate_groups = sum(1 for count in fingerprints.values() if count > 1)
    return {
        "notification_count": len(relevant),
        "notifications": public_rows,
        "duplicate_notification_groups": duplicate_groups,
        "routine_scheduler_success_noise_count": len(routine_noise_ids),
        "system_notifications_missing_action_context_count": len(missing_action_context_ids),
        "quality_ok": duplicate_groups == 0 and not routine_noise_ids and not missing_action_context_ids,
    }


def build_day36_shadow_endurance_report(
    db,
    *,
    session_id: int,
    user_id: int | None = None,
    expected_revision: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Certify one retained four-hour session without synthesizing elapsed time."""

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
    revision = expected_revision or current_revision()

    retained = _verify_retained_report(session)
    final_report = dict(retained.get("report") or {})
    reconciliation = dict(final_report.get("reconciliation") or {})
    safety = dict(final_report.get("safety") or {})
    quality = dict(final_report.get("quality") or {})

    persisted_elapsed = _seconds_between(session.started_at, session.completed_at)
    report_elapsed = _seconds_between(final_report.get("started_at"), final_report.get("completed_at"))
    measured = float(final_report.get("measured_duration_seconds") or 0.0)

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

    checks = {
        "session_completed": session.status == "completed",
        "target_is_exact_4h": session.target_evidence_type == DAY36_TARGET
        and int(session.requested_duration_seconds or 0) == DAY36_SECONDS,
        "persisted_elapsed_at_least_4h": persisted_elapsed is not None and persisted_elapsed >= DAY36_SECONDS,
        "retained_report_elapsed_at_least_4h": measured >= DAY36_SECONDS
        and report_elapsed is not None
        and report_elapsed >= DAY36_SECONDS,
        "persisted_and_report_timestamps_match": (
            _iso(session.started_at) == _iso(final_report.get("started_at"))
            and _iso(session.completed_at) == _iso(final_report.get("completed_at"))
        ),
        "retained_report_hash_valid": bool(retained["valid"]),
        "retained_report_qualification_eligible": final_report.get("qualification_eligible") is True,
        "candidate_revision_matches_exact_runtime": str(session.candidate_revision) == str(revision),
        "continuous_cycle_coverage": bool(coverage["continuous_cycle_coverage"]),
        "memory_telemetry_present": bool(coverage["memory"]["telemetry_present"]),
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
    checks["phase11_quality_gate_passed"] = bool(quality) and all(
        bool(value) for value in quality.values()
    )

    report: dict[str, Any] = {
        "version": DAY36_ENDURANCE_VERSION,
        "session_id": int(session.id),
        "user_id": int(session.user_id),
        "candidate_revision": str(session.candidate_revision),
        "verification_revision": str(revision),
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
        "memory": coverage["memory"],
        "cycle_coverage": {key: value for key, value in coverage.items() if key != "memory"},
        "browser_cleanup": browser_cleanup,
        "notification_quality": notifications,
        "manual_review": {
            "count": len(reviews),
            "open_or_in_progress_review_ids": open_reviews,
        },
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
    report["day37_entry_eligible"] = report["passed"]
    report["report_sha256"] = canonical_hash(report)
    return report


__all__ = [
    "DAY36_ENDURANCE_VERSION",
    "DAY36_SECONDS",
    "DAY36_TARGET",
    "build_day36_shadow_endurance_report",
]
