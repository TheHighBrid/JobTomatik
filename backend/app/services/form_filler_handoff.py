"""Handoff-capable ATS runner backed by a retained localhost CDP browser."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_registry import detect_ats_adapter
from app.services.browser_navigation import (
    is_allowed_url,
    is_fake_url,
    navigate_job_board_listing,
    now_iso,
)
from app.services.browser_runtime import launch_retainable_browser
from app.services.control_engine import CONTROL_ENGINE_VERSION
from app.services.form_filler_v3 import _fill_step_fields

_RESUMABLE_REASONS = {
    "captcha_detected",
    "mfa_required",
    "login_required",
    "anti_bot_challenge",
}


def _promote_deferred_captcha_boundary(flow: Any, log: List[Dict[str, Any]]) -> None:
    """Preserve a passive CAPTCHA boundary when field review ends the ATS flow first.

    The ATS flow deliberately fills safe fields before returning to the user. When a
    field also needs review, the flow can return before its second CAPTCHA check. The
    original deferred-CAPTCHA log entry is durable evidence that the same live page
    still requires a human challenge, so promote it into a resumable review item before
    the retained browser is evaluated.
    """
    if not getattr(flow, "requires_manual_review", False):
        return
    if any(
        str(item.get("reason_code") or "") == "captcha_detected"
        for item in getattr(flow, "review_items", []) or []
    ):
        return

    deferred = next(
        (
            entry
            for entry in reversed(log)
            if entry.get("action") == "captcha_widget_deferred_until_manual_handoff"
        ),
        None,
    )
    if not deferred:
        return

    step_number = int(deferred.get("step") or getattr(flow, "steps_completed", 0) or 1)
    details = {
        "adapter": getattr(flow, "adapter_name", deferred.get("adapter") or "generic"),
        "adapter_version": getattr(flow, "adapter_version", "1.0.0"),
        "step": step_number,
        "handoff_stage": "post_fill_field_review",
        "fields_filled": int(getattr(flow, "fields_filled", 0) or 0),
        "control_evidence_count": len(getattr(flow, "control_evidence", []) or []),
        "upload_evidence_count": len(getattr(flow, "upload_evidence", []) or []),
        "submit_clicked": False,
        "promoted_from_deferred_challenge": True,
    }
    flow.review_items.append({
        "reason_code": "captcha_detected",
        "summary": "A CAPTCHA or human-verification challenge requires manual completion.",
        "details": details,
    })
    event = {
        "action": "ats_deferred_challenge_promoted_for_handoff",
        "adapter": details["adapter"],
        "adapter_version": details["adapter_version"],
        "step": step_number,
        "reason_code": "captcha_detected",
        "fields_filled": details["fields_filled"],
        "control_evidence_count": details["control_evidence_count"],
        "upload_evidence_count": details["upload_evidence_count"],
        "submit_clicked": False,
        "ts": now_iso(),
    }
    flow.step_evidence.append(event)
    log.append(dict(event))


def _resumable_boundary(result: Dict[str, Any]) -> bool:
    if not result.get("requires_manual_review"):
        return False
    reasons = {
        str(item.get("reason_code") or "")
        for item in result.get("review_items") or []
    }
    if reasons & _RESUMABLE_REASONS:
        return True
    text = str(result.get("error") or "").lower()
    return any(term in text for term in ("captcha", "mfa", "verification code", "sign in", "login"))


async def fill_and_submit_application_with_handoff(
    job_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    log: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "success": False,
        "dry_run": dry_run,
        "url": job_url,
        "log": log,
        "submitted_at": None,
        "error": None,
        "fields_filled": 0,
        "requires_manual_review": False,
        "review_items": [],
        "control_engine_version": CONTROL_ENGINE_VERSION,
        "control_evidence": [],
        "upload_evidence": [],
        "step_evidence": [],
        "validation_errors": [],
        "confirmation_evidence": [],
        "ready_to_submit": False,
        "ats_adapter": "generic",
        "ats_adapter_version": "1.0.0",
        "handoff_snapshot": None,
    }
    if not is_allowed_url(job_url):
        result["error"] = "Invalid or unsupported job URL"
        result["requires_manual_review"] = True
        return result
    if is_fake_url(job_url):
        result["error"] = "Placeholder URL; manual application required"
        result["requires_manual_review"] = True
        return result

    runtime = None
    retained = False
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            runtime = await launch_retainable_browser(playwright)
            page = runtime.page
            log.append({"action": "navigate", "url": job_url, "ts": now_iso()})
            try:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeoutError:
                    log.append({"action": "network_idle_timeout", "ts": now_iso()})
            except PlaywrightTimeoutError:
                log.append({"action": "navigation_timeout", "ts": now_iso()})

            target = await navigate_job_board_listing(page, log)
            result.update({
                key: target[key]
                for key in ("application_url", "contact_email")
                if target.get(key)
            })
            if target.get("manual_review_only"):
                result["requires_manual_review"] = True
                result["success"] = bool(dry_run)
                result["error"] = target.get("reason")
                return result

            adapter = await detect_ats_adapter(page, page.url)
            result["ats_adapter"] = adapter.name
            result["ats_adapter_version"] = adapter.version
            log.append({
                "action": "ats_adapter_detected",
                "adapter": adapter.name,
                "version": adapter.version,
                "ts": now_iso(),
            })

            async def fill_step(surface: Any, step_number: int) -> Dict[str, Any]:
                return await _fill_step_fields(
                    surface,
                    profile=user_profile,
                    cover_letter=cover_letter,
                    resume_path=resume_path,
                    log=log,
                    step_number=step_number,
                )

            flow = await run_ats_application_flow(
                page,
                adapter,
                fill_step=fill_step,
                dry_run=dry_run,
                log=log,
            )
            _promote_deferred_captcha_boundary(flow, log)
            result.update(flow.as_dict())
            result["ats_adapter"] = flow.adapter_name
            result["ats_adapter_version"] = flow.adapter_version
            if flow.success and not dry_run:
                result["submitted_at"] = now_iso()

            if _resumable_boundary(result):
                snapshot = await runtime.capture_snapshot(metadata={
                    "dry_run": dry_run,
                    "adapter": flow.adapter_name,
                    "adapter_version": flow.adapter_version,
                    "fields_filled": flow.fields_filled,
                    "steps_completed": flow.steps_completed,
                })
                result["handoff_snapshot"] = snapshot
                retained = True
                log.append({
                    "action": "browser_handoff_retained",
                    "provider": snapshot["browser_provider"],
                    "browser_session_id": snapshot["browser_session_id"],
                    "current_fingerprint": snapshot["current_fingerprint"],
                    "ts": now_iso(),
                })
    except ImportError:
        result["error"] = "Playwright not installed"
        result["requires_manual_review"] = True
    except Exception as exc:
        result["error"] = str(exc)
        result["requires_manual_review"] = True
        log.append({"action": "error", "detail": str(exc)[:300], "ts": now_iso()})
    finally:
        if runtime is not None and not retained:
            runtime.terminate(remove_profile=False)

    return result
