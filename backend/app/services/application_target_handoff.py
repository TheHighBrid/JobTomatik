from __future__ import annotations

from typing import Any, Dict

from app.models.application import Application
from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.services.application_target import (
    is_valid_application_target,
    record_application_target,
)
from app.services.ats_base import page_fingerprint
from app.services.browser_navigation import external_target_from_browser, now_iso


_INSTALLED = False
_TASK_PERSISTENCE_INSTALLED = False
_ORIGINAL_VERIFY = None
_ORIGINAL_RESUME = None
_ORIGINAL_HANDOFF_TASK_RUN = None


def _is_target_navigation_session(session: ManualHandoffSession) -> bool:
    metadata = dict(session.handoff_metadata or {})
    return (
        session.challenge_type == HandoffChallengeType.navigation.value
        or bool(metadata.get("target_resolution_only"))
        or metadata.get("stage") == "application_target_resolution"
    )


def _source_url(session: ManualHandoffSession) -> str:
    metadata = dict(session.handoff_metadata or {})
    return str(metadata.get("source_listing_url") or session.current_url or "")


async def _target_page(context: Any, target_url: str, fallback: Any) -> Any:
    for candidate in reversed(list(context.pages)):
        if str(getattr(candidate, "url", "") or "") == target_url:
            return candidate
    return fallback


def install_application_target_handoff_support() -> None:
    global _INSTALLED, _ORIGINAL_VERIFY, _ORIGINAL_RESUME
    if _INSTALLED:
        return

    from app.services import browser_handoff

    _ORIGINAL_VERIFY = browser_handoff.verify_browser_handoff_completion
    _ORIGINAL_RESUME = browser_handoff.resume_handoff_application

    async def target_aware_verify(session: ManualHandoffSession):
        if not _is_target_navigation_session(session):
            return await _ORIGINAL_VERIFY(session)

        playwright, _, context, page = await browser_handoff._connect_local_cdp(session)
        try:
            source_url = _source_url(session)
            target_url = await external_target_from_browser(page, source_url)
            valid = bool(target_url and is_valid_application_target(source_url, target_url))
            if valid:
                session.current_url = target_url
                session.handoff_metadata = {
                    **dict(session.handoff_metadata or {}),
                    "resolved_target_url": target_url,
                }
                active_page = await _target_page(context, target_url, page)
            else:
                active_page = page
            fingerprint = await page_fingerprint(active_page)
            return browser_handoff.BrowserVerification(
                challenge_cleared=valid,
                provider=session.browser_provider,
                current_url=target_url or page.url,
                current_fingerprint=fingerprint,
                evidence={
                    "verification_method": "external_application_target",
                    "source_listing_url": source_url,
                    "application_target_url": target_url,
                    "target_resolved": valid,
                },
            )
        finally:
            await browser_handoff._disconnect(playwright)

    async def target_aware_resume(
        session: ManualHandoffSession,
        *,
        user_profile: Dict[str, Any],
        cover_letter: str,
        resume_path: str,
        dry_run: bool,
    ) -> Dict[str, Any]:
        if not _is_target_navigation_session(session):
            return await _ORIGINAL_RESUME(
                session,
                user_profile=user_profile,
                cover_letter=cover_letter,
                resume_path=resume_path,
                dry_run=dry_run,
            )

        playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
        try:
            source_url = _source_url(session)
            target_url = await external_target_from_browser(page, source_url)
            if not target_url or not is_valid_application_target(source_url, target_url):
                return {
                    "success": False,
                    "dry_run": dry_run,
                    "url": page.url,
                    "source_listing_url": source_url,
                    "application_target_status": "requires_human",
                    "log": [{
                        "action": "application_target_still_unresolved",
                        "url": page.url,
                        "ts": now_iso(),
                    }],
                    "error": "The browser is still on the discovery listing. Click Apply and wait for the employer page to open.",
                    "fields_filled": 0,
                    "requires_manual_review": True,
                    "review_items": [{
                        "reason_code": "application_target_required",
                        "summary": "The employer application destination has not opened yet.",
                        "details": {"stage": "application_target_resolution", "submit_clicked": False},
                    }],
                    "ready_to_submit": False,
                    "target_resolution_only": True,
                }
            session.current_url = target_url
            session.handoff_metadata = {
                **dict(session.handoff_metadata or {}),
                "resolved_target_url": target_url,
                "target_resolution_only": False,
            }
        finally:
            await browser_handoff._disconnect(playwright)

        result = await _ORIGINAL_RESUME(
            session,
            user_profile=user_profile,
            cover_letter=cover_letter,
            resume_path=resume_path,
            dry_run=dry_run,
        )
        result["source_listing_url"] = source_url
        result["application_target_url"] = target_url
        result["application_target_status"] = "resolved"
        result["target_resolution_only"] = False
        result.setdefault("log", []).insert(0, {
            "action": "application_target_resolved_during_handoff",
            "source_listing_url": source_url,
            "application_target_url": target_url,
            "ts": now_iso(),
        })
        return result

    browser_handoff.verify_browser_handoff_completion = target_aware_verify
    browser_handoff.resume_handoff_application = target_aware_resume

    # API and task modules import these functions directly, so update their bound
    # references when they are already loaded.
    try:
        from app.api import handoffs as handoff_api
        handoff_api.verify_browser_handoff_completion = target_aware_verify
    except ImportError:
        pass
    try:
        from app.tasks import handoffs as handoff_tasks
        handoff_tasks.resume_handoff_application = target_aware_resume
    except (ImportError, AttributeError):
        pass

    _INSTALLED = True


def install_application_target_handoff_task_persistence() -> None:
    """Persist a target URL returned by the resumed browser task."""
    global _TASK_PERSISTENCE_INSTALLED, _ORIGINAL_HANDOFF_TASK_RUN
    if _TASK_PERSISTENCE_INSTALLED:
        return

    from app.tasks import handoffs as handoff_tasks

    task = handoff_tasks.resume_handoff_session_task
    _ORIGINAL_HANDOFF_TASK_RUN = task.run

    def wrapped_run(handoff_public_id: str, **kwargs):
        result = _ORIGINAL_HANDOFF_TASK_RUN(handoff_public_id, **kwargs)
        if not isinstance(result, dict):
            return result
        target_url = str(result.get("application_target_url") or "")
        source_url = str(result.get("source_listing_url") or "")
        if not target_url or not is_valid_application_target(source_url, target_url):
            return result

        db = handoff_tasks.SessionLocal()
        try:
            session = db.query(ManualHandoffSession).filter(
                ManualHandoffSession.public_id == handoff_public_id
            ).first()
            app = (
                db.query(Application).filter(Application.id == session.application_id).first()
                if session
                else None
            )
            if app:
                app.source_listing_url = app.source_listing_url or source_url
                record_application_target(
                    db,
                    app,
                    target_url=target_url,
                    method="human_handoff_navigation",
                    metadata={"handoff_public_id": handoff_public_id},
                )
                db.commit()
        finally:
            db.close()
        return result

    task.run = wrapped_run
    _TASK_PERSISTENCE_INSTALLED = True


__all__ = [
    "install_application_target_handoff_support",
    "install_application_target_handoff_task_persistence",
]