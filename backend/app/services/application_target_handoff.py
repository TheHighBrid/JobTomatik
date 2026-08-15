from __future__ import annotations

from typing import Any, Dict

from app.models.application import Application
from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.services.application_entry import application_form_evidence, open_application_entry
from app.services.application_target import (
    is_valid_application_target,
    record_application_target,
)
from app.services.ats_base import page_fingerprint
from app.services.ats_registry import detect_ats_adapter
from app.services.browser_navigation import external_target_from_browser, now_iso


_INSTALLED = False
_TASK_PERSISTENCE_INSTALLED = False
_ORIGINAL_VERIFY = None
_ORIGINAL_RESUME = None
_ORIGINAL_CONNECT = None
_ORIGINAL_HANDOFF_TASK_RUN = None
_target_evidence_from_browser = None

_ATS_REASON_TO_CHALLENGE = {
    "captcha_detected": HandoffChallengeType.captcha.value,
    "mfa_required": HandoffChallengeType.mfa.value,
    "login_required": HandoffChallengeType.login.value,
    "anti_bot_challenge": HandoffChallengeType.anti_bot.value,
}


def _metadata(session: ManualHandoffSession) -> Dict[str, Any]:
    return dict(session.handoff_metadata or {})


def _is_target_navigation_session(session: ManualHandoffSession) -> bool:
    metadata = _metadata(session)
    if (
        metadata.get("target_resolution_only") is False
        and metadata.get("stage") == "ats_application"
        and metadata.get("resolved_target_url")
    ):
        return False
    return (
        session.challenge_type == HandoffChallengeType.navigation.value
        or bool(metadata.get("target_resolution_only"))
        or str(metadata.get("stage") or "").startswith("application_target_")
    )


def _is_target_security_session(session: ManualHandoffSession) -> bool:
    metadata = _metadata(session)
    return (
        _is_target_navigation_session(session)
        and session.challenge_type != HandoffChallengeType.navigation.value
        and str(metadata.get("stage") or "").startswith("application_target_")
    )


def _source_url(session: ManualHandoffSession) -> str:
    metadata = _metadata(session)
    return str(metadata.get("source_listing_url") or session.current_url or "")


async def _target_page(context: Any, target_url: str, fallback: Any) -> Any:
    for candidate in reversed(list(context.pages)):
        if str(getattr(candidate, "url", "") or "") == target_url:
            return candidate
    return fallback


async def _page_target_id(context: Any, page: Any) -> str:
    """Read Chromium's durable top-level target id for a connected page."""
    cdp_session = None
    try:
        cdp_session = await context.new_cdp_session(page)
        target_info = await cdp_session.send("Target.getTargetInfo")
        return str((target_info.get("targetInfo") or {}).get("targetId") or "")
    except Exception:
        return ""
    finally:
        if cdp_session is not None:
            try:
                await cdp_session.detach()
            except Exception:
                pass


async def _retained_target_page(
    context: Any,
    session: ManualHandoffSession,
    fallback: Any,
) -> Any | None:
    """Select only the tab bound to this target-resolution handoff.

    A Chromium target id survives same-tab cross-origin navigation, unlike the stored
    URL. Legacy target handoffs without a target id may use an exact URL match, but
    they must never fall back to an arbitrary final context page.
    """
    pages = list(getattr(context, "pages", []) or [])
    metadata = _metadata(session)
    expected_target_id = str(metadata.get("controlled_page_target_id") or "")
    if expected_target_id:
        for candidate in pages:
            if await _page_target_id(context, candidate) == expected_target_id:
                return candidate
        return None

    expected_url = str(session.current_url or "")
    if expected_url:
        for candidate in pages:
            if str(getattr(candidate, "url", "") or "") == expected_url:
                return candidate

    if _is_target_navigation_session(session):
        return None
    return fallback


def _next_challenge_type(result: Dict[str, Any]) -> str | None:
    for item in result.get("review_items") or []:
        challenge = _ATS_REASON_TO_CHALLENGE.get(str(item.get("reason_code") or ""))
        if challenge:
            return challenge
    return None


async def _fallback_target_evidence(
    page: Any,
    source_url: str,
    log: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compatibility proof for imports that run before the correlated runtime binds."""
    observed = await external_target_from_browser(page, source_url, log)
    if not observed:
        return {
            "status": "none",
            "application_url": None,
            "application_form_detected": False,
            "form_evidence": {},
            "trusted_ats_adapter": None,
            "trusted_ats_adapter_version": None,
        }
    active_page = await _target_page(page.context, observed, page)
    form_detected = False
    form_evidence: Dict[str, Any] = {}
    try:
        evidence = await application_form_evidence(active_page)
        form_detected = bool(evidence.present)
        form_evidence = evidence.as_dict()
    except Exception:
        pass
    adapter_name = ""
    adapter_version = ""
    try:
        adapter = await detect_ats_adapter(active_page, observed)
        adapter_name = str(getattr(adapter, "name", "") or "")
        adapter_version = str(getattr(adapter, "version", "") or "")
    except Exception:
        pass
    trusted_ats = bool(
        adapter_name and adapter_name.lower() not in {"generic", "unknown"}
    )
    if not form_detected and not trusted_ats:
        return {
            "status": "none",
            "application_url": None,
            "application_form_detected": False,
            "form_evidence": {},
            "trusted_ats_adapter": None,
            "trusted_ats_adapter_version": None,
        }
    return {
        "status": "resolved",
        "application_url": observed,
        "application_form_detected": form_detected,
        "form_evidence": form_evidence,
        "trusted_ats_adapter": adapter_name or None,
        "trusted_ats_adapter_version": adapter_version or None,
    }


async def _observed_target_evidence(
    page: Any,
    source_url: str,
    log: list[Dict[str, Any]],
) -> Dict[str, Any]:
    resolver = _target_evidence_from_browser
    if callable(resolver):
        return await resolver(page, source_url, log)
    return await _fallback_target_evidence(page, source_url, log)


async def _resolve_target_after_human_boundary(
    page: Any,
    source_url: str,
) -> Dict[str, Any]:
    log: list[Dict[str, Any]] = []
    observed = await _observed_target_evidence(page, source_url, log)
    if observed.get("status") == "resolved":
        return {
            "application_url": observed.get("application_url"),
            "resolution_method": "existing_correlated_application_target",
            "application_form_detected": bool(observed.get("application_form_detected")),
            "form_evidence": dict(observed.get("form_evidence") or {}),
            "trusted_ats_adapter": observed.get("trusted_ats_adapter"),
            "trusted_ats_adapter_version": observed.get("trusted_ats_adapter_version"),
            "log": log,
        }
    if observed.get("status") == "pending":
        # Do not open a fresh entry scope here. Doing so would classify an already-open
        # correlated popup as baseline and permanently hide it when its redirect lands.
        return {
            "application_url": None,
            "application_form_detected": False,
            "form_evidence": {},
            "trusted_ats_adapter": None,
            "trusted_ats_adapter_version": None,
            "correlated_target_pending": True,
            "log": log,
        }
    resolved = await open_application_entry(page, log)
    resolved["log"] = log
    return resolved


def install_application_target_handoff_support() -> None:
    global _INSTALLED, _ORIGINAL_VERIFY, _ORIGINAL_RESUME, _ORIGINAL_CONNECT
    if _INSTALLED:
        return

    from app.services import browser_handoff

    _ORIGINAL_VERIFY = browser_handoff.verify_browser_handoff_completion
    _ORIGINAL_RESUME = browser_handoff.resume_handoff_application
    _ORIGINAL_CONNECT = browser_handoff._connect_local_cdp

    async def target_aware_connect(session: ManualHandoffSession):
        connected = await _ORIGINAL_CONNECT(session)
        if not _is_target_navigation_session(session):
            return connected
        playwright, browser, context, fallback_page = connected
        selected = await _retained_target_page(context, session, fallback_page)
        if selected is None:
            await browser_handoff._disconnect(playwright)
            raise browser_handoff.BrowserHandoffUnavailable(
                "The retained application-target tab can no longer be identified safely."
            )
        return playwright, browser, context, selected

    # Bind the exact-tab selector before invoking any captured verify/resume function.
    # Those original functions resolve _connect_local_cdp from their module at runtime.
    browser_handoff._connect_local_cdp = target_aware_connect

    async def target_aware_verify(session: ManualHandoffSession):
        if not _is_target_navigation_session(session):
            return await _ORIGINAL_VERIFY(session)
        if _is_target_security_session(session):
            return await _ORIGINAL_VERIFY(session)

        playwright, _, context, page = await browser_handoff._connect_local_cdp(session)
        try:
            source_url = _source_url(session)
            observed = await _observed_target_evidence(page, source_url, [])
            target_url = str(observed.get("application_url") or "")
            form_detected = bool(observed.get("application_form_detected"))
            trusted_ats = str(observed.get("trusted_ats_adapter") or "")
            target_proven = bool(form_detected or trusted_ats)
            valid = bool(
                observed.get("status") == "resolved"
                and target_url
                and target_proven
                and is_valid_application_target(
                    source_url,
                    target_url,
                    application_form_detected=form_detected,
                )
            )
            if valid:
                session.current_url = target_url
                session.handoff_metadata = {
                    **_metadata(session),
                    "resolved_target_url": target_url,
                    "application_form_detected": form_detected,
                    "trusted_ats_adapter": trusted_ats or None,
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
                    "verification_method": "correlated_application_target",
                    "source_listing_url": source_url,
                    "application_target_url": target_url or None,
                    "target_resolved": valid,
                    "application_form_detected": form_detected,
                    "trusted_ats_adapter": trusted_ats or None,
                    "correlated_target_pending": observed.get("status") == "pending",
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
        source_url = _source_url(session)
        try:
            doorway = await _resolve_target_after_human_boundary(page, source_url)
            target_url = str(doorway.get("application_url") or "")
            form_detected = bool(doorway.get("application_form_detected"))
            trusted_ats = str(doorway.get("trusted_ats_adapter") or "")
            target_proven = bool(form_detected or trusted_ats)
            if (
                not target_url
                or not target_proven
                or not is_valid_application_target(
                    source_url,
                    target_url,
                    application_form_detected=form_detected,
                )
            ):
                return {
                    "success": False,
                    "dry_run": dry_run,
                    "url": page.url,
                    "source_listing_url": source_url,
                    "application_target_status": "failed",
                    "log": [
                        *list(doorway.get("log") or []),
                        {
                            "action": "application_target_still_unresolved_after_boundary",
                            "url": page.url,
                            "manual_apply_click_requested": False,
                            "correlated_target_pending": bool(
                                doorway.get("correlated_target_pending")
                            ),
                            "ts": now_iso(),
                        },
                    ],
                    "error": (
                        "The security boundary cleared, but JobTomatik still could not "
                        "prove the application form or supported ATS target automatically."
                    ),
                    "fields_filled": 0,
                    "requires_manual_review": False,
                    "review_items": [],
                    "ready_to_submit": False,
                    "target_resolution_only": True,
                }
            session.current_url = target_url
            session.handoff_metadata = {
                **_metadata(session),
                "resolved_target_url": target_url,
                "target_resolution_only": False,
                "stage": "ats_application",
                "application_form_detected": form_detected,
                "form_evidence": dict(doorway.get("form_evidence") or {}),
                "trusted_ats_adapter": trusted_ats or None,
                "trusted_ats_adapter_version": doorway.get("trusted_ats_adapter_version"),
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
        next_challenge = _next_challenge_type(result)
        if next_challenge:
            session.challenge_type = next_challenge
            session.handoff_metadata = {
                **_metadata(session),
                "stage": "ats_application",
                "target_resolution_only": False,
            }
        result["source_listing_url"] = source_url
        result["application_target_url"] = target_url
        result["application_target_status"] = "resolved"
        result["application_form_detected"] = form_detected
        result["trusted_ats_adapter"] = trusted_ats or None
        result["target_resolution_only"] = False
        result.setdefault("log", []).insert(0, {
            "action": "application_target_resolved_after_human_boundary",
            "source_listing_url": source_url,
            "application_target_url": target_url,
            "application_form_detected": form_detected,
            "trusted_ats_adapter": trusted_ats or None,
            "automatic_apply_navigation": True,
            "ts": now_iso(),
        })
        return result

    browser_handoff.verify_browser_handoff_completion = target_aware_verify
    browser_handoff.resume_handoff_application = target_aware_resume

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
        form_detected = bool(result.get("application_form_detected"))
        trusted_ats = str(result.get("trusted_ats_adapter") or "")
        if (
            not target_url
            or not (form_detected or trusted_ats)
            or not is_valid_application_target(
                source_url,
                target_url,
                application_form_detected=form_detected,
            )
        ):
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
                    method="automatic_navigation_after_human_boundary",
                    metadata={
                        "handoff_public_id": handoff_public_id,
                        "application_form_detected": form_detected,
                        "trusted_ats_adapter": trusted_ats or None,
                    },
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
