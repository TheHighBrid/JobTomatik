"""Cross-source operational observability and low-noise incident notifications.

This module is read-heavy. It derives source and adapter health from existing durable
records and may create deduplicated in-app notifications. It never changes adapter
maturity, application state, approval state, or submission authorization.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import joinedload

from app.models.application import (
    Application,
    ApplicationAutomationState,
)
from app.models.intelligence import AgentRun
from app.models.material import ApplicationMaterial
from app.models.notification import Notification, NotificationType
from app.services.adapter_health import build_adapter_health_report
from app.services.operations_policy import evaluate_circuit_breaker_policy, platform_key_for_url


INCIDENT_KIND = "operational_incident"
DIGEST_KIND = "operational_digest"
DEFAULT_WINDOW_HOURS = 24
DEFAULT_DEDUPE_HOURS = 24


def _naive_utc(value: datetime | None) -> datetime:
    value = value or datetime.utcnow()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _naive_utc(value).replace(microsecond=0).isoformat() + "Z"


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _source_diagnostics(run: AgentRun) -> list[dict[str, Any]]:
    result = dict(run.result or {})
    rows = result.get("source_diagnostics") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def build_source_health_report(
    db,
    user_id: int,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    failure_threshold: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _naive_utc(now)
    bounded_window = max(1, min(int(window_hours), 24 * 30))
    threshold = max(1, min(int(failure_threshold), 100))
    since = current - timedelta(hours=bounded_window)

    runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.user_id == user_id,
            AgentRun.created_at >= since,
        )
        .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
        .all()
    )
    discovery_runs = [
        run for run in runs
        if (run.run_context or {}).get("pipeline") == "public_ats_discovery_v1"
    ]

    buckets: dict[str, dict[str, Any]] = {}
    recent_statuses: dict[str, list[str]] = defaultdict(list)
    for run in discovery_runs:
        for row in _source_diagnostics(run):
            source = str(row.get("source") or "unknown").strip().lower()
            bucket = buckets.setdefault(source, {
                "source": source,
                "observations": 0,
                "successful_observations": 0,
                "failed_observations": 0,
                "zero_result_observations": 0,
                "result_count": 0,
                "error_counts": Counter(),
                "last_observed_at": None,
            })
            bucket["observations"] += 1
            status = str(row.get("status") or "unknown").lower()
            recent_statuses[source].append(status)
            if status == "success":
                bucket["successful_observations"] += 1
                result_count = max(0, int(row.get("result_count") or 0))
                bucket["result_count"] += result_count
                if result_count == 0:
                    bucket["zero_result_observations"] += 1
            else:
                bucket["failed_observations"] += 1
                code = str(row.get("error_code") or "unknown")
                bucket["error_counts"][code] += 1
            observed_at = _naive_utc(run.completed_at or run.created_at)
            if bucket["last_observed_at"] is None or observed_at > bucket["last_observed_at"]:
                bucket["last_observed_at"] = observed_at

    sources: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for source in sorted(buckets):
        bucket = buckets[source]
        statuses = recent_statuses[source]
        consecutive_failures = 0
        for status in reversed(statuses):
            if status == "success":
                break
            consecutive_failures += 1
        failure_count = int(bucket["failed_observations"])
        success_count = int(bucket["successful_observations"])
        observations = int(bucket["observations"])
        success_rate = round(success_count / observations, 4) if observations else 0.0

        source_alerts: list[dict[str, Any]] = []
        if consecutive_failures >= threshold:
            source_alerts.append({
                "domain": "source",
                "entity": source,
                "code": "source_breakage",
                "severity": "critical",
                "count": consecutive_failures,
                "detail": f"{source} has failed {consecutive_failures} consecutive discovery observations.",
                "recovery_path": "/adapter-health",
            })
        elif failure_count >= threshold:
            source_alerts.append({
                "domain": "source",
                "entity": source,
                "code": "source_failure_spike",
                "severity": "warning",
                "count": failure_count,
                "detail": f"{source} recorded repeated discovery failures in the selected window.",
                "recovery_path": "/adapter-health",
            })

        zero_count = int(bucket["zero_result_observations"])
        if success_count >= threshold and zero_count == success_count:
            source_alerts.append({
                "domain": "source",
                "entity": source,
                "code": "source_zero_results",
                "severity": "warning",
                "count": zero_count,
                "detail": f"{source} completed successfully but returned zero jobs repeatedly.",
                "recovery_path": "/scheduler",
            })

        alerts.extend(source_alerts)
        sources.append({
            "source": source,
            "status": (
                "critical" if any(a["severity"] == "critical" for a in source_alerts)
                else "degraded" if source_alerts
                else "healthy" if observations else "no_data"
            ),
            "observations": observations,
            "successful_observations": success_count,
            "failed_observations": failure_count,
            "zero_result_observations": zero_count,
            "result_count": int(bucket["result_count"]),
            "success_rate": success_rate,
            "consecutive_failures": consecutive_failures,
            "error_counts": dict(sorted(bucket["error_counts"].items())),
            "last_observed_at": _iso_utc(bucket["last_observed_at"]),
            "alerts": source_alerts,
        })

    return {
        "generated_at": _iso_utc(current),
        "window_hours": bounded_window,
        "failure_threshold": threshold,
        "run_count": len(discovery_runs),
        "sources": sources,
        "alerts": alerts,
        "summary": {
            "source_count": len(sources),
            "observations": sum(item["observations"] for item in sources),
            "failures": sum(item["failed_observations"] for item in sources),
            "results": sum(item["result_count"] for item in sources),
            "alert_count": len(alerts),
            "critical_alert_count": sum(1 for item in alerts if item["severity"] == "critical"),
        },
    }


def _application_platform(application: Application) -> str:
    job = application.job
    if not job:
        return "generic"
    raw = dict(job.raw_data or {})
    return platform_key_for_url(str(raw.get("selected_apply_url") or job.url or ""))


def _affected_applications(db, user_id: int, platform: str, code: str, since: datetime) -> list[int]:
    applications = (
        db.query(Application)
        .options(joinedload(Application.job), joinedload(Application.manual_reviews))
        .filter(Application.user_id == user_id)
        .all()
    )
    ids: list[int] = []
    for application in applications:
        if _application_platform(application) != platform:
            continue
        state = str(application.automation_state or "")
        updated = _naive_utc(application.updated_at or application.created_at)
        if updated < since:
            continue
        matches = False
        if code == "submission_uncertain" and state == ApplicationAutomationState.submission_uncertain.value:
            matches = True
        elif code == "repeated_failures" and state == ApplicationAutomationState.failed.value:
            matches = True
        else:
            reason_codes = {
                str(review.reason_code)
                for review in application.manual_reviews or []
                if _naive_utc(review.created_at) >= since
            }
            if code == "validation_failure_spike" and "validation_error" in reason_codes:
                matches = True
            elif code == "source_breakage" and reason_codes & {
                "unsupported_platform", "unsupported_control", "step_navigation_failed", "automation_error"
            }:
                matches = True
            elif code == "login_lockout_risk" and reason_codes & {"login_required", "mfa_required"}:
                matches = True
        if matches:
            ids.append(int(application.id))
    return ids[:20]


def _material_alerts(db, user_id: int, since: datetime) -> list[dict[str, Any]]:
    materials = (
        db.query(ApplicationMaterial)
        .join(Application, ApplicationMaterial.application_id == Application.id)
        .filter(
            Application.user_id == user_id,
            ApplicationMaterial.created_at >= since,
            ApplicationMaterial.status == "needs_review",
        )
        .order_by(ApplicationMaterial.created_at.desc())
        .all()
    )
    if not materials:
        return []
    application_ids = sorted({int(item.application_id) for item in materials})[:20]
    return [{
        "domain": "material",
        "entity": "application_materials",
        "code": "material_integrity_review",
        "severity": "warning",
        "count": len(materials),
        "detail": "Generated application materials require evidence or factual-integrity review.",
        "application_ids": application_ids,
        "recovery_path": f"/applications/{application_ids[0]}" if len(application_ids) == 1 else "/evidence-materials",
    }]


def build_operational_observability_report(
    db,
    user_id: int,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    failure_threshold: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _naive_utc(now)
    bounded_window = max(1, min(int(window_hours), 24 * 30))
    since = current - timedelta(hours=bounded_window)

    adapter = build_adapter_health_report(
        db,
        user_id,
        window_hours=bounded_window,
        failure_threshold=failure_threshold,
        now=current,
    )
    threshold = int(adapter.get("failure_threshold") or failure_threshold or 3)
    source = build_source_health_report(
        db,
        user_id,
        window_hours=bounded_window,
        failure_threshold=threshold,
        now=current,
    )

    incidents: list[dict[str, Any]] = []
    for alert in adapter.get("alerts") or []:
        platform = str(alert.get("platform") or "generic")
        code = str(alert.get("code") or "adapter_health")
        app_ids = _affected_applications(db, user_id, platform, code, since)
        incidents.append({
            "domain": "adapter",
            "entity": platform,
            "code": code,
            "severity": alert.get("severity") or "warning",
            "count": int(alert.get("count") or 0),
            "detail": alert.get("detail"),
            "application_ids": app_ids,
            "recovery_path": f"/applications/{app_ids[0]}" if len(app_ids) == 1 else "/adapter-health",
        })

    incidents.extend(source.get("alerts") or [])
    incidents.extend(_material_alerts(db, user_id, since))

    circuit = evaluate_circuit_breaker_policy(db, user_id, now=current)
    if not circuit.allowed:
        incidents.append({
            "domain": "policy",
            "entity": "autopilot",
            "code": circuit.code,
            "severity": "critical",
            "count": int(circuit.metadata.get("failure_count") or 1),
            "detail": circuit.reason,
            "application_ids": list(circuit.metadata.get("application_ids") or [])[:20],
            "recovery_path": "/operations",
        })

    for incident in incidents:
        incident.setdefault("application_ids", [])
        incident["fingerprint"] = _fingerprint([
            INCIDENT_KIND,
            incident.get("domain"),
            incident.get("entity"),
            incident.get("code"),
            incident.get("severity"),
        ])

    incidents.sort(
        key=lambda item: (
            item.get("severity") == "critical",
            int(item.get("count") or 0),
            str(item.get("domain") or ""),
            str(item.get("entity") or ""),
        ),
        reverse=True,
    )

    recent_runs = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id, AgentRun.created_at >= since)
        .all()
    )
    saved_jobs = sum(
        int((run.result or {}).get("saved") or 0)
        for run in recent_runs
        if (run.run_context or {}).get("pipeline") == "public_ats_discovery_v1"
    )

    return {
        "generated_at": _iso_utc(current),
        "window_hours": bounded_window,
        "adapter_health": adapter,
        "source_health": source,
        "incidents": incidents,
        "activity": {
            "new_jobs_saved": saved_jobs,
            "application_attempts": int((adapter.get("summary") or {}).get("attempts") or 0),
            "confirmed": int((adapter.get("summary") or {}).get("confirmed") or 0),
            "manual_review": int((adapter.get("summary") or {}).get("manual_review") or 0),
        },
        "summary": {
            "incident_count": len(incidents),
            "critical_incident_count": sum(1 for item in incidents if item.get("severity") == "critical"),
            "source_alert_count": int((source.get("summary") or {}).get("alert_count") or 0),
            "adapter_alert_count": int((adapter.get("summary") or {}).get("alert_count") or 0),
        },
        "invariants": {
            "read_only_report": True,
            "cannot_change_adapter_maturity": True,
            "cannot_authorize_submission": True,
            "cannot_send_recruiter_outreach": True,
        },
    }


def _recent_operational_notifications(db, user_id: int, since: datetime) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.type == NotificationType.system,
            Notification.created_at >= since,
        )
        .all()
    )


def sync_operational_notifications(
    db,
    user_id: int,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    failure_threshold: int | None = None,
    dedupe_hours: int = DEFAULT_DEDUPE_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _naive_utc(now)
    report = build_operational_observability_report(
        db,
        user_id,
        window_hours=window_hours,
        failure_threshold=failure_threshold,
        now=current,
    )
    since = current - timedelta(hours=max(1, min(int(dedupe_hours), 24 * 30)))
    recent = _recent_operational_notifications(db, user_id, since)
    existing = {
        str((item.data or {}).get("fingerprint"))
        for item in recent
        if (item.data or {}).get("kind") == INCIDENT_KIND
    }

    created = 0
    deduplicated = 0
    for incident in report["incidents"]:
        fingerprint = incident["fingerprint"]
        if fingerprint in existing:
            deduplicated += 1
            continue
        severity = str(incident.get("severity") or "warning")
        entity = str(incident.get("entity") or "system").replace("_", " ")
        code = str(incident.get("code") or "incident").replace("_", " ")
        db.add(Notification(
            user_id=user_id,
            type=NotificationType.system,
            title=f"{'Critical' if severity == 'critical' else 'Warning'}: {entity} {code}",
            message=str(incident.get("detail") or "Operational attention is required."),
            data={
                "kind": INCIDENT_KIND,
                "fingerprint": fingerprint,
                "domain": incident.get("domain"),
                "entity": incident.get("entity"),
                "code": incident.get("code"),
                "severity": severity,
                "count": int(incident.get("count") or 0),
                "application_ids": list(incident.get("application_ids") or []),
                "recovery_path": incident.get("recovery_path"),
                "generated_at": report["generated_at"],
            },
        ))
        existing.add(fingerprint)
        created += 1

    # Routine activity is collapsed into one UTC-day digest rather than emitting one
    # success notification for every scheduled search cycle.
    digest_key = current.date().isoformat()
    digest_fp = _fingerprint([DIGEST_KIND, user_id, digest_key])
    digest_exists = any(
        (item.data or {}).get("kind") == DIGEST_KIND
        and (item.data or {}).get("fingerprint") == digest_fp
        for item in recent
    )
    activity = report["activity"]
    activity_count = sum(int(value or 0) for value in activity.values())
    digest_created = False
    if activity_count and not digest_exists:
        db.add(Notification(
            user_id=user_id,
            type=NotificationType.system,
            title="JobTomatik daily operations digest",
            message=(
                f"{activity['new_jobs_saved']} jobs saved, {activity['application_attempts']} application attempts, "
                f"{activity['confirmed']} confirmed, {activity['manual_review']} requiring review."
            ),
            data={
                "kind": DIGEST_KIND,
                "fingerprint": digest_fp,
                "date_utc": digest_key,
                "activity": activity,
                "incident_count": report["summary"]["incident_count"],
                "recovery_path": "/adapter-health",
            },
        ))
        digest_created = True

    return {
        "user_id": user_id,
        "incidents_detected": len(report["incidents"]),
        "notifications_created": created,
        "notifications_deduplicated": deduplicated,
        "digest_created": digest_created,
        "summary": report["summary"],
    }


__all__ = [
    "DEFAULT_DEDUPE_HOURS",
    "DEFAULT_WINDOW_HOURS",
    "DIGEST_KIND",
    "INCIDENT_KIND",
    "build_operational_observability_report",
    "build_source_health_report",
    "sync_operational_notifications",
]
