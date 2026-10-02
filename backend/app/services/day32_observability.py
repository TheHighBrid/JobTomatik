"""Day 32 actionable observability and low-noise notification policy.

This module wraps the existing operational observability report instead of replacing it.
It adds Day 31 material-integrity drift detection, exact application links, and explicit
operator recovery actions. It never changes application state, adapter maturity,
approvals, or submission authorization.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import joinedload

from app.models.application import Application
from app.models.material import ApplicationMaterial
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.autonomous_material_verification import verify_material_integrity
from app.services.operational_observability import (
    DEFAULT_DEDUPE_HOURS,
    DEFAULT_WINDOW_HOURS,
    DIGEST_KIND,
    INCIDENT_KIND,
    build_operational_observability_report,
)


DAY32_OBSERVABILITY_VERSION = "actionable-observability-v1"


def _naive_utc(value: datetime | None) -> datetime:
    value = value or datetime.utcnow()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _application_links(application_ids: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "application_id": int(application_id),
            "path": f"/applications/{int(application_id)}",
        }
        for application_id in sorted({int(value) for value in application_ids})
    ]


def _recovery_actions(code: str) -> list[str]:
    mapping = {
        "submission_uncertain": [
            "Open each affected application and inspect confirmation evidence.",
            "Do not retry final submit while submission state is uncertain.",
            "Resolve the application to confirmed, failed, or manual review before another attempt.",
        ],
        "validation_failure_spike": [
            "Open the affected applications and compare the failed field/control evidence.",
            "Verify stored answer policy and form-control mapping before retrying.",
            "Keep automatic submission blocked until the validation regression is understood.",
        ],
        "source_breakage": [
            "Inspect the source or adapter diagnostics and the most recent failures.",
            "Keep the unhealthy source backed off while the failure repeats.",
            "Resume only after a successful source/adapter verification run.",
        ],
        "login_lockout_risk": [
            "Stop repeated login or MFA retries for the affected platform.",
            "Resolve authentication manually and confirm account access.",
            "Resume automation only after the lockout risk is cleared.",
        ],
        "circuit_breaker_open": [
            "Inspect the clustered failures that tripped the circuit breaker.",
            "Keep automation paused while the breaker is open.",
            "Resume only after the underlying failure cluster is resolved and the breaker closes.",
        ],
        "platform_circuit_breaker_open": [
            "Inspect the affected platform failure cluster.",
            "Keep that platform paused while its circuit breaker is open.",
            "Resume the platform only after a clean verification cycle.",
        ],
        "evidence_mismatch": [
            "Open the affected application and inspect the material-integrity blockers.",
            "Reconfirm or rebuild the canonical resume and applicant evidence sources.",
            "Regenerate and re-verify application materials before any application attempt.",
        ],
        "material_integrity_review": [
            "Open the affected application material review.",
            "Resolve missing or low-confidence applicant evidence.",
            "Regenerate materials after the evidence is corrected.",
        ],
        "repeated_failures": [
            "Open the affected applications and identify the common failure stage.",
            "Keep automatic retries bounded while the failure repeats.",
            "Verify the fix with a dry-run or synthetic path before resuming.",
        ],
        "low_confirmation_rate": [
            "Inspect recent terminal attempts and their confirmation evidence.",
            "Confirm the adapter is recognizing real success states reliably.",
            "Keep uncertain outcomes in review instead of treating them as submitted.",
        ],
        "source_failure_spike": [
            "Inspect recent source diagnostics and error codes.",
            "Allow source backoff to suppress repeated failing requests.",
            "Confirm recovery with a successful discovery observation.",
        ],
        "source_zero_results": [
            "Review the source query and target configuration.",
            "Check whether the source changed response shape or stopped returning expected postings.",
            "Confirm a non-zero discovery result before treating the source as healthy.",
        ],
    }
    return list(mapping.get(code, [
        "Open the linked operations view and inspect the underlying evidence.",
        "Keep consequential automation blocked until the incident is understood.",
        "Record recovery evidence before resuming the affected operation.",
    ]))


def _enrich_incident(incident: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(incident)
    application_ids = [int(value) for value in enriched.get("application_ids") or []]
    enriched["application_ids"] = application_ids
    enriched["application_links"] = _application_links(application_ids)
    enriched["recovery_actions"] = _recovery_actions(str(enriched.get("code") or ""))
    if len(application_ids) == 1:
        enriched["recovery_path"] = f"/applications/{application_ids[0]}"
    return enriched


def _latest_stamped_materials(db, user_id: int, since: datetime) -> list[ApplicationMaterial]:
    rows = (
        db.query(ApplicationMaterial)
        .options(joinedload(ApplicationMaterial.application))
        .join(Application, ApplicationMaterial.application_id == Application.id)
        .filter(
            Application.user_id == user_id,
            ApplicationMaterial.created_at >= since,
        )
        .order_by(
            ApplicationMaterial.application_id.asc(),
            ApplicationMaterial.material_type.asc(),
            ApplicationMaterial.version.desc(),
            ApplicationMaterial.id.desc(),
        )
        .all()
    )
    latest: dict[tuple[int, str], ApplicationMaterial] = {}
    for material in rows:
        snapshot = dict(material.source_snapshot or {})
        if "day31_material_verification" not in snapshot:
            continue
        key = (int(material.application_id), str(material.material_type))
        latest.setdefault(key, material)
    return list(latest.values())


def _material_evidence_mismatch_incidents(
    db,
    user: User,
    since: datetime,
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for material in _latest_stamped_materials(db, int(user.id), since):
        application = material.application
        if application is None:
            continue
        result = verify_material_integrity(db, material, application, user)
        if result.get("valid") is not False:
            continue
        blockers = sorted({str(value) for value in result.get("blockers") or []})
        application_id = int(application.id)
        incidents.append({
            "domain": "material",
            "entity": f"application_{application_id}",
            "code": "evidence_mismatch",
            "severity": "critical",
            "count": max(1, len(blockers)),
            "detail": (
                "Prepared application material no longer matches its verified content, "
                "evidence, or resume snapshot."
            ),
            "application_ids": [application_id],
            "application_links": _application_links([application_id]),
            "recovery_path": f"/applications/{application_id}",
            "recovery_actions": _recovery_actions("evidence_mismatch"),
            "material_id": int(material.id),
            "material_type": str(material.material_type),
            "blockers": blockers,
            "fingerprint": _fingerprint([
                INCIDENT_KIND,
                "material",
                application_id,
                material.id,
                "evidence_mismatch",
                ",".join(blockers),
            ]),
        })
    return incidents


def build_day32_observability_report(
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
    report = build_operational_observability_report(
        db,
        user_id,
        window_hours=bounded_window,
        failure_threshold=failure_threshold,
        now=current,
    )

    user = db.query(User).filter(User.id == user_id).first()
    base_incidents = [_enrich_incident(dict(item)) for item in report.get("incidents") or []]
    mismatch_incidents = (
        _material_evidence_mismatch_incidents(db, user, since) if user is not None else []
    )
    incidents = base_incidents + mismatch_incidents
    incidents.sort(
        key=lambda item: (
            item.get("severity") == "critical",
            int(item.get("count") or 0),
            str(item.get("code") or ""),
        ),
        reverse=True,
    )

    report["incidents"] = incidents
    summary = dict(report.get("summary") or {})
    summary["incident_count"] = len(incidents)
    summary["critical_incident_count"] = sum(
        1 for item in incidents if item.get("severity") == "critical"
    )
    summary["evidence_mismatch_count"] = sum(
        1 for item in incidents if item.get("code") == "evidence_mismatch"
    )
    report["summary"] = summary
    report["day32_contract"] = {
        "version": DAY32_OBSERVABILITY_VERSION,
        "adapter_success_dashboard": True,
        "source_success_dashboard": True,
        "submission_uncertain_alert": True,
        "repeated_validation_failure_alert": True,
        "source_breakage_alert": True,
        "lockout_risk_alert": True,
        "circuit_breaker_alert": True,
        "evidence_mismatch_alert": True,
        "exact_application_links": True,
        "recovery_actions": True,
        "routine_successes_digest_only": True,
    }
    return report


def _recent_system_notifications(db, user_id: int, since: datetime) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.type == NotificationType.system,
            Notification.created_at >= since,
        )
        .all()
    )


def sync_day32_operational_notifications(
    db,
    user_id: int,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    failure_threshold: int | None = None,
    dedupe_hours: int = DEFAULT_DEDUPE_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _naive_utc(now)
    report = build_day32_observability_report(
        db,
        user_id,
        window_hours=window_hours,
        failure_threshold=failure_threshold,
        now=current,
    )
    since = current - timedelta(hours=max(1, min(int(dedupe_hours), 24 * 30)))
    recent = _recent_system_notifications(db, user_id, since)
    existing = {
        str((item.data or {}).get("fingerprint"))
        for item in recent
        if (item.data or {}).get("kind") == INCIDENT_KIND
        and (item.data or {}).get("fingerprint")
    }

    created = 0
    deduplicated = 0
    for incident in report["incidents"]:
        fingerprint = str(incident.get("fingerprint") or _fingerprint([
            INCIDENT_KIND,
            incident.get("domain"),
            incident.get("entity"),
            incident.get("code"),
            incident.get("severity"),
        ]))
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
                "observability_version": DAY32_OBSERVABILITY_VERSION,
                "domain": incident.get("domain"),
                "entity": incident.get("entity"),
                "code": incident.get("code"),
                "severity": severity,
                "count": int(incident.get("count") or 0),
                "application_ids": list(incident.get("application_ids") or []),
                "application_links": list(incident.get("application_links") or []),
                "recovery_path": incident.get("recovery_path"),
                "recovery_actions": list(incident.get("recovery_actions") or []),
                "blockers": list(incident.get("blockers") or []),
                "material_id": incident.get("material_id"),
                "generated_at": report.get("generated_at"),
            },
        ))
        existing.add(fingerprint)
        created += 1

    digest_key = current.date().isoformat()
    digest_fp = _fingerprint([DIGEST_KIND, user_id, digest_key])
    digest_exists = any(
        (item.data or {}).get("kind") == DIGEST_KIND
        and (item.data or {}).get("fingerprint") == digest_fp
        for item in recent
    )
    activity = dict(report.get("activity") or {})
    activity_count = sum(int(value or 0) for value in activity.values())
    digest_created = False
    if activity_count and not digest_exists:
        db.add(Notification(
            user_id=user_id,
            type=NotificationType.system,
            title="JobTomatik daily operations digest",
            message=(
                f"{activity.get('new_jobs_saved', 0)} jobs saved, "
                f"{activity.get('application_attempts', 0)} application attempts, "
                f"{activity.get('confirmed', 0)} confirmed, "
                f"{activity.get('manual_review', 0)} requiring review."
            ),
            data={
                "kind": DIGEST_KIND,
                "fingerprint": digest_fp,
                "observability_version": DAY32_OBSERVABILITY_VERSION,
                "date_utc": digest_key,
                "activity": activity,
                "incident_count": int((report.get("summary") or {}).get("incident_count") or 0),
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
        "summary": report.get("summary") or {},
        "contract": report["day32_contract"],
    }


__all__ = [
    "DAY32_OBSERVABILITY_VERSION",
    "build_day32_observability_report",
    "sync_day32_operational_notifications",
]
