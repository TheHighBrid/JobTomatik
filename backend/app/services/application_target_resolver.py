from __future__ import annotations

from typing import Any, Dict, List

from app.services.application_entry_runtime import open_application_entry
from app.services.application_target import is_valid_application_target
from app.services.browser_navigation import (
    detect_blocking_challenge,
    is_allowed_url,
    is_fake_url,
    is_job_board_url,
    now_iso,
)
from app.services.browser_runtime import (
    launch_application_browser,
    release_application_browser,
)
from app.services.employer_application_entry import continue_from_employer_landing
from app.services.listing_availability import detect_closed_listing


_RESUMABLE_TARGET_REASONS = {
    "captcha_detected",
    "mfa_required",
    "login_required",
    "anti_bot_challenge",
}


async def _controlled_page_target_id(page: Any) -> str:
    """Return the Chromium target id for the exact retained top-level tab."""
    context = getattr(page, "context", None)
    if context is None:
        return ""
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


async def resolve_application_target_with_browser(source_url: str) -> Dict[str, Any]:
    """Resolve a listing into a form or a certified hosted ATS entry point.

    Ordinary Apply doorways are automated. A retained handoff is created only for an
    observed security or identity boundary. An arbitrary employer job-detail URL is
    never treated as sufficient target evidence merely because it is off the job board.
    """
    log: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "success": False,
        "dry_run": True,
        "url": source_url,
        "source_listing_url": source_url,
        "application_target_url": None,
        "application_target_status": "unresolved",
        "log": log,
        "submitted_at": None,
        "error": None,
        "fields_filled": 0,
        "requires_manual_review": False,
        "review_items": [],
        "handoff_snapshot": None,
        "target_resolution_only": True,
        "terminal_reason": None,
        "retryable": True,
    }
    if not is_allowed_url(source_url) or is_fake_url(source_url):
        result["application_target_status"] = "failed"
        result["error"] = "Invalid or placeholder job listing URL"
        result["terminal_reason"] = "invalid_listing_url"
        result["retryable"] = False
        return result

    runtime = None
    retained = False
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            runtime = await launch_application_browser(playwright)
            page = runtime.page
            log.append({
                "action": "application_target_navigation_started",
                "url": source_url,
                "ts": now_iso(),
            })
            try:
                await page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeoutError:
                    log.append({"action": "application_target_network_idle_timeout", "ts": now_iso()})
            except PlaywrightTimeoutError:
                log.append({"action": "application_target_navigation_timeout", "ts": now_iso()})

            closed = await detect_closed_listing(page)
            if closed:
                result.update({
                    "application_target_status": "failed",
                    "requires_manual_review": False,
                    "error": closed["summary"],
                    "url": closed.get("url") or page.url or source_url,
                    "terminal_reason": "listing_closed",
                    "retryable": False,
                    "listing_availability": "closed",
                    "listing_closed_evidence": closed,
                })
                log.append({
                    "action": "application_listing_closed",
                    "source_url": source_url,
                    "current_url": result["url"],
                    "matched_text": closed.get("matched_text"),
                    "manual_handoff_created": False,
                    "retryable": False,
                    "ts": now_iso(),
                })
                return result

            target = await open_application_entry(page, log)
            target_url = str(target.get("application_url") or "")
            form_detected = bool(target.get("application_form_detected"))

            current_url = str(getattr(page, "url", "") or target_url or source_url)
            if not form_detected and current_url and not is_job_board_url(current_url):
                continued = await continue_from_employer_landing(
                    page,
                    source_url=source_url,
                    log=log,
                )
                if continued:
                    target = continued
                    target_url = str(target.get("application_url") or "")
                    form_detected = bool(target.get("application_form_detected"))

            trusted_ats = str(target.get("trusted_ats_adapter") or "")
            trusted_ats_version = str(target.get("trusted_ats_adapter_version") or "")
            target_is_proven = bool(form_detected or trusted_ats)
            if target_url and target_is_proven and is_valid_application_target(
                source_url,
                target_url,
                application_form_detected=form_detected,
            ):
                result.update({
                    "success": True,
                    "application_target_url": target_url,
                    "application_target_status": "resolved",
                    "resolution_method": target.get("resolution_method") or "automatic_apply_navigation",
                    "application_form_detected": form_detected,
                    "form_evidence": target.get("form_evidence") or {},
                    "trusted_ats_adapter": trusted_ats or None,
                    "trusted_ats_adapter_version": trusted_ats_version or None,
                    "url": target_url,
                    "retryable": False,
                })
                log.append({
                    "action": "application_target_proven",
                    "url": target_url,
                    "application_form_detected": form_detected,
                    "trusted_ats_adapter": trusted_ats or None,
                    "ts": now_iso(),
                })
                return result

            closed = await detect_closed_listing(page)
            if closed:
                result.update({
                    "application_target_status": "failed",
                    "requires_manual_review": False,
                    "error": closed["summary"],
                    "url": closed.get("url") or page.url or source_url,
                    "terminal_reason": "listing_closed",
                    "retryable": False,
                    "listing_availability": "closed",
                    "listing_closed_evidence": closed,
                })
                log.append({
                    "action": "application_listing_closed",
                    "source_url": source_url,
                    "current_url": result["url"],
                    "matched_text": closed.get("matched_text"),
                    "manual_handoff_created": False,
                    "retryable": False,
                    "ts": now_iso(),
                })
                return result

            challenge = await detect_blocking_challenge(page)
            reason_code = str((challenge or {}).get("reason_code") or "")
            if challenge and reason_code in _RESUMABLE_TARGET_REASONS:
                result.update({
                    "application_target_status": "requires_human",
                    "requires_manual_review": True,
                    "error": challenge.get("summary"),
                    "review_items": [challenge],
                    "retryable": False,
                })
                controlled_target_id = await _controlled_page_target_id(page)
                snapshot_metadata = {
                    "dry_run": True,
                    "stage": "application_target_security_boundary",
                    "source_listing_url": source_url,
                    "adapter": "listing_resolver",
                    "adapter_version": "2.3.0",
                    "reason_code": reason_code,
                }
                if controlled_target_id:
                    snapshot_metadata["controlled_page_target_id"] = controlled_target_id
                snapshot = await runtime.capture_snapshot(metadata=snapshot_metadata)
                result["handoff_snapshot"] = snapshot
                retained = True
                log.append({
                    "action": "application_target_security_handoff_retained",
                    "reason_code": reason_code,
                    "browser_session_id": snapshot["browser_session_id"],
                    "current_url": snapshot["current_url"],
                    "controlled_page_target_id_recorded": bool(controlled_target_id),
                    "ts": now_iso(),
                })
                return result

            current_url = str(getattr(page, "url", "") or source_url)
            result.update({
                "application_target_status": "failed",
                "requires_manual_review": False,
                "error": (
                    "JobTomatik could not reach an application form or a certified ATS "
                    "entry point from the job page. No CAPTCHA, login, MFA, or anti-bot "
                    "boundary was observed, so no manual handoff was created."
                ),
                "url": current_url,
                "terminal_reason": "application_form_unavailable",
            })
            log.append({
                "action": "application_target_automatic_resolution_failed",
                "source_url": source_url,
                "current_url": current_url,
                "manual_handoff_created": False,
                "ts": now_iso(),
            })
    except ImportError:
        result["application_target_status"] = "failed"
        result["error"] = "Playwright not installed"
        result["terminal_reason"] = "browser_runtime_unavailable"
    except Exception as exc:
        result["application_target_status"] = "failed"
        result["error"] = str(exc)
        result["terminal_reason"] = "application_target_resolution_error"
        log.append({
            "action": "application_target_resolution_error",
            "detail": str(exc)[:300],
            "ts": now_iso(),
        })
    finally:
        if runtime is not None:
            await release_application_browser(
                runtime,
                retain_controlled_page=retained,
            )

    return result
