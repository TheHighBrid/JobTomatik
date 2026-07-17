"""User-scoped adapter health metrics and operational alerts.

The report is derived from existing application lifecycle state, manual-review
records, and adapter maturity. It contains no applicant answers or document
contents and is safe to expose through an authenticated operations endpoint.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable

from sqlalchemy.orm import joinedload

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewReason,
)
from app.services.operations_policy import platform_key_for_url
from app.services.operations_settings import get_operations_settings
from app.services.unattended_policy import live_platform_maturities


ATTEMPT_STATES = {
    ApplicationAutomationState.applying.value,
    ApplicationAutomationState.needs_review.value,
    ApplicationAutomationState.submission_uncertain.value,
    ApplicationAutomationState.submitted.value,
    ApplicationAutomationState.confirmed.value,
    ApplicationAutomationState.failed.value,
}
SUCCESS_STATES = {
    ApplicationAutomationState.submitted.value,
    ApplicationAutomationState.confirmed.value,
}
BREAKAGE_REASONS = {
    ManualReviewReason.unsupported_platform.value,
    ManualReviewReason.unsupported_control.value,
    ManualReviewReason.step_navigation_failed.value,
    ManualReviewReason.automation_error.value,
}
LOGIN_RISK_REASONS = {
    ManualReviewReason.login_required.value,
    ManualReviewReason.mfa_required.value,
}


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _iso_utc(value: datetime | None) -> str | None:
    normalized = _naive_utc(value)
    if normalized is None:
        return None
    return normalized.replace(microsecond=0).isoformat() + "Z"


def _application_time(application: Application) -> datetime | None:
    return _naive_utc(
        application.last_submission_attempt_at
        or application.updated_at
        or application.created_at
    )


def _application_platform(application: Application) -> str:
    job = application.job
    if not job:
        return "generic"
    raw = dict(job.raw_data or {})
    target_url = raw.get("selected_apply_url") or job.url or ""
    return platform_key_for_url(str(target_url))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _new_bucket(platform: str, maturity: str | None) -> Dict[str, Any]:
    return {
        "platform": platform,
        "maturity": maturity,
        "attempts": 0,
        "successful": 0,
        "submitted": 0,
        "confirmed": 0,
        "manual_review": 0,
        "submission_uncertain": 0,
        "failed": 0,
        "active": 0,
        "reason_counts": Counter(),
        "last_attempt_at": None,
    }


def _alert(
    platform: str,
    code: str,
    severity: str,
    count: int,
    detail: str,
) -> Dict[str, Any]:
    return {
        "platform": platform,
        "code": code,
        "severity": severity,
        "count": int(count),
        "detail": detail,
    }


def _platform_alerts(
    bucket: Dict[str, Any],
    failure_threshold: int,
) -> list[Dict[str, Any]]:
    platform = bucket["platform"]
    reasons: Counter[str] = bucket["reason_counts"]
    alerts: list[Dict[str, Any]] = []

    uncertain = int(bucket["submission_uncertain"])
    if uncertain:
        alerts.append(_alert(
            platform,
            "submission_uncertain",
            "critical",
            uncertain,
            "At least one application lacks sufficient confirmation evidence.",
        ))

    failed = int(bucket["failed"])
    if failed >= failure_threshold:
        alerts.append(_alert(
            platform,
            "repeated_failures",
            "critical",
            failed,
            f"Failed applications reached the configured threshold of {failure_threshold}.",
        ))

    validation_failures = int(reasons.get(ManualReviewReason.validation_error.value, 0))
    if validation_failures >= failure_threshold:
        alerts.append(_alert(
            platform,
            "validation_failure_spike",
            "warning",
            validation_failures,
            "Repeated validation failures indicate an answer or control regression.",
        ))

    breakage_count = sum(int(reasons.get(reason, 0)) for reason in BREAKAGE_REASONS)
    if breakage_count >= failure_threshold:
        alerts.append(_alert(
            platform,
            "source_breakage",
            "critical",
            breakage_count,
            "Repeated adapter, control, or navigation failures suggest source breakage.",
        ))

    login_risk_count = sum(int(reasons.get(reason, 0)) for reason in LOGIN_RISK_REASONS)
    if login_risk_count >= failure_threshold:
        alerts.append(_alert(
            platform,
            "login_lockout_risk",
            "critical",
            login_risk_count,
            "Repeated login or MFA handoffs may indicate expired credentials or lockout risk.",
        ))

    terminal = int(bucket["successful"]) + failed + uncertain
    success_rate = _rate(int(bucket["successful"]), terminal)
    if terminal >= failure_threshold and success_rate < 0.5:
        alerts.append(_alert(
            platform,
            "low_confirmation_rate",
            "warning",
            terminal - int(bucket["successful"]),
            "Fewer than half of terminal attempts produced sufficient submission evidence.",
        ))

    return alerts


def _status_for(attempts: int, alerts: Iterable[Dict[str, Any]]) -> str:
    alerts = list(alerts)
    if attempts <= 0:
        return "no_data"
    if any(item["severity"] == "critical" for item in alerts):
        return "critical"
    if alerts:
        return "degraded"
    return "healthy"


def build_adapter_health_report(
    db,
    user_id: int,
    *,
    window_hours: int = 24,
    failure_threshold: int | None = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Build a deterministic, user-scoped adapter health report."""

    normalized_now = _naive_utc(now or datetime.utcnow()) or datetime.utcnow()
    bounded_window = max(1, min(int(window_hours), 24 * 30))
    since = normalized_now - timedelta(hours=bounded_window)
    settings = get_operations_settings()
    threshold = max(1, int(failure_threshold or settings.failure_threshold))
    maturities = live_platform_maturities()

    applications = (
        db.query(Application)
        .options(
            joinedload(Application.job),
            joinedload(Application.manual_reviews),
        )
        .filter(Application.user_id == user_id)
        .all()
    )

    buckets: Dict[str, Dict[str, Any]] = {}
    for application in applications:
        attempt_time = _application_time(application)
        if attempt_time is None or attempt_time < since:
            continue

        state = str(
            application.automation_state
            or ApplicationAutomationState.preparing.value
        )
        attempted = bool(application.submission_attempt_count) or state in ATTEMPT_STATES
        if not attempted:
            continue

        platform = _application_platform(application)
        bucket = buckets.setdefault(
            platform,
            _new_bucket(platform, maturities.get(platform)),
        )
        bucket["attempts"] += 1
        if bucket["last_attempt_at"] is None or attempt_time > bucket["last_attempt_at"]:
            bucket["last_attempt_at"] = attempt_time

        if state in SUCCESS_STATES:
            bucket["successful"] += 1
        if state == ApplicationAutomationState.submitted.value:
            bucket["submitted"] += 1
        elif state == ApplicationAutomationState.confirmed.value:
            bucket["confirmed"] += 1
        elif state == ApplicationAutomationState.needs_review.value:
            bucket["manual_review"] += 1
        elif state == ApplicationAutomationState.submission_uncertain.value:
            bucket["submission_uncertain"] += 1
        elif state == ApplicationAutomationState.failed.value:
            bucket["failed"] += 1
        elif state == ApplicationAutomationState.applying.value:
            bucket["active"] += 1

        for review in application.manual_reviews or []:
            review_time = _naive_utc(review.created_at)
            if review_time is None or review_time < since:
                continue
            bucket["reason_counts"][str(review.reason_code)] += 1

    platform_reports: list[Dict[str, Any]] = []
    alerts: list[Dict[str, Any]] = []
    for platform in sorted(buckets):
        bucket = buckets[platform]
        platform_alerts = _platform_alerts(bucket, threshold)
        alerts.extend(platform_alerts)
        attempts = int(bucket["attempts"])
        terminal = (
            int(bucket["successful"])
            + int(bucket["submission_uncertain"])
            + int(bucket["failed"])
        )
        reason_counts: Counter[str] = bucket["reason_counts"]
        platform_reports.append({
            "platform": platform,
            "maturity": bucket["maturity"],
            "status": _status_for(attempts, platform_alerts),
            "attempts": attempts,
            "successful": int(bucket["successful"]),
            "submitted": int(bucket["submitted"]),
            "confirmed": int(bucket["confirmed"]),
            "manual_review": int(bucket["manual_review"]),
            "submission_uncertain": int(bucket["submission_uncertain"]),
            "failed": int(bucket["failed"]),
            "active": int(bucket["active"]),
            "success_rate": _rate(int(bucket["successful"]), terminal),
            "manual_review_rate": _rate(int(bucket["manual_review"]), attempts),
            "reason_counts": dict(sorted(reason_counts.items())),
            "last_attempt_at": _iso_utc(bucket["last_attempt_at"]),
            "alerts": platform_alerts,
        })

    summary = {
        "attempts": sum(item["attempts"] for item in platform_reports),
        "successful": sum(item["successful"] for item in platform_reports),
        "confirmed": sum(item["confirmed"] for item in platform_reports),
        "manual_review": sum(item["manual_review"] for item in platform_reports),
        "submission_uncertain": sum(
            item["submission_uncertain"] for item in platform_reports
        ),
        "failed": sum(item["failed"] for item in platform_reports),
        "active": sum(item["active"] for item in platform_reports),
        "alert_count": len(alerts),
        "critical_alert_count": sum(
            1 for item in alerts if item["severity"] == "critical"
        ),
    }
    summary["status"] = _status_for(summary["attempts"], alerts)

    return {
        "generated_at": _iso_utc(normalized_now),
        "window_hours": bounded_window,
        "failure_threshold": threshold,
        "summary": summary,
        "platforms": platform_reports,
        "alerts": alerts,
    }


__all__ = ["build_adapter_health_report"]
