"""Create deduplicated in-app notifications from adapter health alerts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.models.notification import Notification, NotificationType
from app.services.adapter_health import build_adapter_health_report


NOTIFICATION_KIND = "adapter_health_alert"
DEFAULT_DEDUPE_HOURS = 24


def _naive_utc(value: datetime | None) -> datetime:
    value = value or datetime.utcnow()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _fingerprint(alert: Dict[str, Any]) -> str:
    source = "|".join([
        NOTIFICATION_KIND,
        str(alert.get("platform") or "generic"),
        str(alert.get("code") or "unknown"),
        str(alert.get("severity") or "warning"),
    ])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _title(alert: Dict[str, Any]) -> str:
    platform = str(alert.get("platform") or "Adapter").replace("_", " ").title()
    severity = str(alert.get("severity") or "warning").lower()
    prefix = "Critical" if severity == "critical" else "Warning"
    code = str(alert.get("code") or "health alert").replace("_", " ")
    return f"{prefix}: {platform} {code}"


def sync_adapter_health_notifications(
    db,
    user_id: int,
    *,
    window_hours: int = 24,
    failure_threshold: int | None = None,
    dedupe_hours: int = DEFAULT_DEDUPE_HOURS,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Persist new health alerts without repeating the same alert every run.

    The caller owns the transaction. Returned data contains only counters and
    fingerprints, never applicant answers or uploaded document contents.
    """

    normalized_now = _naive_utc(now)
    bounded_dedupe = max(1, min(int(dedupe_hours), 24 * 30))
    since = normalized_now - timedelta(hours=bounded_dedupe)
    report = build_adapter_health_report(
        db,
        user_id,
        window_hours=window_hours,
        failure_threshold=failure_threshold,
        now=normalized_now,
    )

    recent = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.type == NotificationType.system,
            Notification.created_at >= since,
        )
        .all()
    )
    existing = {
        str((item.data or {}).get("fingerprint"))
        for item in recent
        if (item.data or {}).get("kind") == NOTIFICATION_KIND
        and (item.data or {}).get("fingerprint")
    }

    created_fingerprints: list[str] = []
    skipped_fingerprints: list[str] = []
    for alert in report.get("alerts") or []:
        fingerprint = _fingerprint(alert)
        if fingerprint in existing:
            skipped_fingerprints.append(fingerprint)
            continue

        db.add(Notification(
            user_id=user_id,
            type=NotificationType.system,
            title=_title(alert),
            message=str(alert.get("detail") or "Adapter health requires attention."),
            data={
                "kind": NOTIFICATION_KIND,
                "fingerprint": fingerprint,
                "platform": alert.get("platform"),
                "code": alert.get("code"),
                "severity": alert.get("severity"),
                "count": int(alert.get("count") or 0),
                "window_hours": int(report.get("window_hours") or window_hours),
                "generated_at": report.get("generated_at"),
            },
        ))
        existing.add(fingerprint)
        created_fingerprints.append(fingerprint)

    return {
        "user_id": user_id,
        "report_status": (report.get("summary") or {}).get("status"),
        "alerts_detected": len(report.get("alerts") or []),
        "notifications_created": len(created_fingerprints),
        "notifications_deduplicated": len(skipped_fingerprints),
        "created_fingerprints": created_fingerprints,
        "deduplicated_fingerprints": skipped_fingerprints,
    }


__all__ = [
    "DEFAULT_DEDUPE_HOURS",
    "NOTIFICATION_KIND",
    "sync_adapter_health_notifications",
]
