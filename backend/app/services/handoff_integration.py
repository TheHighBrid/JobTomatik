from __future__ import annotations

from typing import Any, Dict

from app.models.application import ManualReviewReason, ManualReviewStatus, ManualReviewTask
from app.services.handoff_notifications import create_handoff_required_notification
from app.services.handoff_session import HandoffSessionError, issue_handoff_session

_INSTALLED = False
_ORIGINAL = None
_RESUMABLE_REASON_VALUES = {
    ManualReviewReason.captcha_detected.value,
    ManualReviewReason.mfa_required.value,
    ManualReviewReason.login_required.value,
    ManualReviewReason.anti_bot_challenge.value,
}


def _reason_value(reason_code) -> str:
    return str(getattr(reason_code, "value", reason_code) or "")


def _handoff_review_reason(result: Dict[str, Any], fallback_reason) -> str:
    """Choose the actual resumable blocker, even when another review came first."""
    for item in result.get("review_items") or []:
        reason = str(item.get("reason_code") or "")
        if reason in _RESUMABLE_REASON_VALUES:
            return reason
    return _reason_value(fallback_reason)


def _attach_handoff_session(
    db,
    app,
    result: Dict[str, Any],
    reason_code,
) -> None:
    snapshot = result.get("handoff_snapshot") or {}
    if not snapshot:
        return

    review_reason = _handoff_review_reason(result, reason_code)
    review = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == app.id,
            ManualReviewTask.reason_code == review_reason,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .order_by(ManualReviewTask.created_at.desc(), ManualReviewTask.id.desc())
        .first()
    )
    if not review:
        return

    metadata = dict(snapshot.get("metadata") or {})
    metadata.update({
        "dry_run": bool(result.get("dry_run", True)),
        "html_snapshot_path": snapshot.get("html_snapshot_path"),
        "adapter": result.get("ats_adapter"),
        "adapter_version": result.get("ats_adapter_version"),
    })
    issued = issue_handoff_session(
        db,
        app,
        review,
        browser_provider=snapshot.get("browser_provider") or "unavailable",
        browser_session_id=snapshot.get("browser_session_id"),
        browser_endpoint=snapshot.get("browser_endpoint"),
        browser_node_id=snapshot.get("browser_node_id"),
        browser_process_id=snapshot.get("browser_process_id"),
        browser_profile_path=snapshot.get("browser_profile_path"),
        active_page_hint=snapshot.get("active_page_hint"),
        current_url=snapshot.get("current_url"),
        current_fingerprint=snapshot.get("current_fingerprint"),
        storage_state_path=snapshot.get("storage_state_path"),
        storage_state_hash=snapshot.get("storage_state_hash"),
        screenshot_path=snapshot.get("screenshot_path"),
        metadata=metadata,
    )
    notification = create_handoff_required_notification(
        db,
        app,
        review,
        issued.session,
    )
    review.details = {
        **dict(review.details or {}),
        "handoff_public_id": issued.session.public_id,
        "handoff_status": issued.session.status,
        "handoff_expires_at": issued.session.expires_at.isoformat(),
        "browser_provider": issued.session.browser_provider,
        "handoff_notification_id": notification.id,
    }
    # Safe metadata may be returned by the Celery result. Secrets remain encrypted
    # and are disclosed only once through the authenticated bootstrap endpoint.
    result["handoff_public_id"] = issued.session.public_id
    result["handoff_expires_at"] = issued.session.expires_at.isoformat()
    result["handoff_notification_id"] = notification.id
    result.pop("handoff_snapshot", None)


def install_handoff_task_integration() -> None:
    """Install an idempotent extension around application review creation."""
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return

    from app.tasks import applications as application_tasks

    _ORIGINAL = application_tasks._create_result_review_tasks

    def wrapped_create_result_review_tasks(db, app, result, method, blocking_url):
        reason_code = _ORIGINAL(db, app, result, method, blocking_url)
        try:
            _attach_handoff_session(db, app, result, reason_code)
        except HandoffSessionError as exc:
            result.setdefault("log", []).append({
                "action": "handoff_session_not_created",
                "reason": str(exc)[:300],
            })
        return reason_code

    application_tasks._create_result_review_tasks = wrapped_create_result_review_tasks
    _INSTALLED = True
