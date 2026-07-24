from __future__ import annotations

from typing import Any, Dict, List

from app.config import get_settings
from app.services.application_target import is_valid_application_target
from app.services.browser_navigation import (
    is_allowed_url,
    is_fake_url,
    navigate_job_board_listing,
    now_iso,
    wait_for_external_application_target,
)
from app.services.browser_runtime import launch_application_browser


async def resolve_application_target_with_browser(source_url: str) -> Dict[str, Any]:
    """Resolve a discovery listing into an employer or ATS application URL.

    The resolver owns only the doorway phase. It never fills an ATS form and never
    treats a completed Celery task as evidence that an application was submitted.
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
    }
    if not is_allowed_url(source_url) or is_fake_url(source_url):
        result["application_target_status"] = "failed"
        result["error"] = "Invalid or placeholder job listing URL"
        return result

    runtime = None
    retained = False
    settings = get_settings()
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            runtime = await launch_application_browser(playwright)
            page = runtime.page
            log.append({"action": "application_target_navigation_started", "url": source_url, "ts": now_iso()})
            try:
                await page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeoutError:
                    log.append({"action": "application_target_network_idle_timeout", "ts": now_iso()})
            except PlaywrightTimeoutError:
                log.append({"action": "application_target_navigation_timeout", "ts": now_iso()})

            target = await navigate_job_board_listing(page, log)
            target_url = str(target.get("application_url") or "")
            if target_url and is_valid_application_target(source_url, target_url):
                result.update({
                    "success": True,
                    "application_target_url": target_url,
                    "application_target_status": "resolved",
                    "resolution_method": target.get("resolution_method") or "browser_navigation",
                    "url": target_url,
                })
                return result

            if target.get("contact_email"):
                result.update({
                    "application_target_status": "requires_human",
                    "requires_manual_review": True,
                    "contact_email": target["contact_email"],
                    "error": target.get("reason") or "Employer accepts applications by email.",
                    "review_items": [{
                        "reason_code": "employer_contact_missing",
                        "summary": target.get("reason") or "Employer accepts applications by email.",
                        "details": {"contact_email": target["contact_email"], "stage": "target_resolution"},
                    }],
                })
                return result

            target_url = await wait_for_external_application_target(
                page,
                source_url,
                timeout_seconds=settings.application_target_human_wait_seconds,
                log=log,
            )
            if target_url and is_valid_application_target(source_url, target_url):
                result.update({
                    "success": True,
                    "application_target_url": target_url,
                    "application_target_status": "resolved",
                    "resolution_method": "human_apply_click",
                    "url": target_url,
                })
                return result

            error = (
                "Open the retained JobTomatik browser and click LinkedIn's Apply button once. "
                "JobTomatik will continue from the employer destination in the same browser session."
            )
            result.update({
                "application_target_status": "requires_human",
                "requires_manual_review": True,
                "error": error,
                "review_items": [{
                    "reason_code": "application_target_required",
                    "summary": "One human Apply click is required to reveal the employer application destination.",
                    "details": {
                        "stage": "application_target_resolution",
                        "source_listing_url": source_url,
                        "submit_clicked": False,
                    },
                }],
            })
            snapshot = await runtime.capture_snapshot(metadata={
                "dry_run": True,
                "stage": "application_target_resolution",
                "source_listing_url": source_url,
                "adapter": "listing_resolver",
                "adapter_version": "1.0.0",
            })
            result["handoff_snapshot"] = snapshot
            retained = True
            log.append({
                "action": "application_target_browser_retained",
                "browser_session_id": snapshot["browser_session_id"],
                "current_url": snapshot["current_url"],
                "ts": now_iso(),
            })
    except ImportError:
        result["application_target_status"] = "failed"
        result["error"] = "Playwright not installed"
    except Exception as exc:
        result["application_target_status"] = "failed"
        result["error"] = str(exc)
        log.append({"action": "application_target_resolution_error", "detail": str(exc)[:300], "ts": now_iso()})
    finally:
        if runtime is not None and not retained:
            runtime.terminate(remove_profile=False)

    return result