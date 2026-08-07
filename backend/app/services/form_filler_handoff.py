"""Handoff-capable ATS runner backed by a retained localhost CDP browser."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.services.application_entry import application_form_evidence, open_application_entry
from app.services.ats_flow import run_ats_application_flow
from app.services.ats_registry import detect_ats_adapter
from app.services.browser_navigation import (
    detect_blocking_challenge,
    is_allowed_url,
    is_fake_url,
    is_job_board_url,
    now_iso,
)
from app.services.browser_runtime import launch_application_browser
from app.services.control_engine import CONTROL_ENGINE_VERSION
from app.services.employer_application_entry import continue_from_employer_landing
from app.services.form_filler_v3 import _fill_step_fields
from app.services.supervised_target_identity import verify_supervised_browser_target

_RESUMABLE_REASONS = {
    "captcha_detected",
    "mfa_required",
    "login_required",
    "anti_bot_challenge",
}


def _promote_deferred_captcha_boundary(flow: Any, log: List[Dict[str, Any]]) -> None:
    """Preserve a passive CAPTCHA boundary when field review ends the ATS flow first."""
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


def _apply_challenge_result(result: Dict[str, Any], challenge: Dict[str, Any]) -> None:
    result["requires_manual_review"] = True
    result["error"] = challenge.get("summary")
    result["review_items"] = [challenge]


async def fill_and_submit_application_with_handoff(
    job_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
    supervised_target: Optional[Mapping[str, Any]] = None,
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
        return result
    if is_fake_url(job_url):
        result["error"] = "Placeholder URL; automatic application unavailable"
        return result

    runtime = None
    retained = False
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            runtime = await launch_application_browser(playwright)
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

            entry = await open_application_entry(page, log)
            entry_url = str(entry.get("application_url") or "")
            entry_form_detected = bool(entry.get("application_form_detected"))

            # A job board can lead to an employer-hosted detail page that has one
            # additional plain Apply doorway. Continue through that page before ATS
            # detection or form filling. Reaching a different domain alone is not a
            # valid reason to stop or create a handoff.
            if entry_url and not entry_form_detected and not is_job_board_url(entry_url):
                continued = await continue_from_employer_landing(
                    page,
                    source_url=job_url,
                    log=log,
                )
                if continued:
                    entry = continued
                    entry_url = str(entry.get("application_url") or "")
                    entry_form_detected = bool(entry.get("application_form_detected"))

            if entry_url:
                result["application_url"] = entry_url
                result["application_entry_method"] = entry.get("resolution_method")
                result["application_form_detected"] = entry_form_detected

            adapter = await detect_ats_adapter(page, page.url)
            result["ats_adapter"] = adapter.name
            result["ats_adapter_version"] = adapter.version
            log.append({
                "action": "ats_adapter_detected",
                "adapter": adapter.name,
                "version": adapter.version,
                "ts": now_iso(),
            })

            form_evidence = await application_form_evidence(page)
            result["form_evidence"] = form_evidence.as_dict()
            if adapter.name == "generic" and not form_evidence.present:
                challenge = await detect_blocking_challenge(page)
                if challenge:
                    _apply_challenge_result(result, challenge)
                else:
                    result["error"] = (
                        "The Apply doorway did not expose an application form. No CAPTCHA, "
                        "login, MFA, or anti-bot boundary was observed, so the browser was "
                        "not handed off."
                    )
                    log.append({
                        "action": "application_form_not_reached",
                        "url": page.url,
                        "adapter": adapter.name,
                        "manual_handoff_created": False,
                        "ts": now_iso(),
                    })
                    return result

            async def fill_step(surface: Any, step_number: int) -> Dict[str, Any]:
                return await _fill_step_fields(
                    surface,
                    profile=user_profile,
                    cover_letter=cover_letter,
                    resume_path=resume_path,
                    log=log,
                    step_number=step_number,
                )

            async def pre_submit_check(current_page: Any, _current_adapter: Any) -> Dict[str, Any]:
                detected = await detect_ats_adapter(current_page, current_page.url)
                return await verify_supervised_browser_target(
                    current_url=current_page.url,
                    adapter_name=detected.name,
                    adapter_version=detected.version,
                    expected_metadata=supervised_target,
                    refresh_official_metadata=True,
                )

            if not result.get("requires_manual_review"):
                flow = await run_ats_application_flow(
                    page,
                    adapter,
                    fill_step=fill_step,
                    dry_run=dry_run,
                    log=log,
                    pre_submit_check=(
                        pre_submit_check
                        if supervised_target and not dry_run
                        else None
                    ),
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
                    "adapter": result.get("ats_adapter"),
                    "adapter_version": result.get("ats_adapter_version"),
                    "fields_filled": int(result.get("fields_filled") or 0),
                    "steps_completed": int(result.get("steps_completed") or 0),
                    "handoff_stage": "post_fill_security_boundary",
                    "supervised_target": dict(supervised_target or {}),
                })
                result["handoff_snapshot"] = snapshot
                retained = True
                log.append({
                    "action": "browser_handoff_retained",
                    "provider": snapshot["browser_provider"],
                    "browser_session_id": snapshot["browser_session_id"],
                    "current_fingerprint": snapshot["current_fingerprint"],
                    "fields_filled": int(result.get("fields_filled") or 0),
                    "supervised_target_locked": bool(supervised_target),
                    "ts": now_iso(),
                })
    except ImportError:
        result["error"] = "Playwright not installed"
    except Exception as exc:
        result["error"] = str(exc)
        log.append({"action": "error", "detail": str(exc)[:300], "ts": now_iso()})
    finally:
        if runtime is not None and not retained:
            runtime.terminate(remove_profile=False)

    return result
