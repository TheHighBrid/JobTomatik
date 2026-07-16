from __future__ import annotations

import hashlib
import os
import signal
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.services.ats_base import page_fingerprint
from app.services.browser_navigation import detect_blocking_challenge
from app.services.handoff_session import decrypt_handoff_secret


class BrowserHandoffError(RuntimeError):
    pass


class BrowserHandoffUnavailable(BrowserHandoffError):
    pass


@dataclass
class BrowserVerification:
    challenge_cleared: bool
    provider: str
    current_url: str
    current_fingerprint: str
    evidence: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "challenge_cleared": self.challenge_cleared,
            "provider": self.provider,
            "current_url": self.current_url,
            "current_fingerprint": self.current_fingerprint,
            **self.evidence,
        }


def current_browser_node_id() -> str:
    return os.getenv("JOBTOMATIK_BROWSER_NODE_ID") or socket.gethostname()


def _require_local_affinity(session: ManualHandoffSession) -> None:
    if session.browser_node_id and session.browser_node_id != current_browser_node_id():
        raise BrowserHandoffUnavailable(
            "The browser lease is attached to another worker node. Session-affinity routing is required."
        )


async def _connect_local_cdp(session: ManualHandoffSession):
    if session.browser_provider != "local_cdp":
        raise BrowserHandoffUnavailable(
            f"Browser provider {session.browser_provider!r} is not available on this node."
        )
    _require_local_affinity(session)
    endpoint = decrypt_handoff_secret(session.encrypted_browser_endpoint)
    if not endpoint:
        raise BrowserHandoffUnavailable("The encrypted browser endpoint is missing or unreadable.")

    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=5000)
    except Exception:
        await playwright.stop()
        raise BrowserHandoffUnavailable("The retained browser process is no longer reachable.")

    contexts = list(browser.contexts)
    if not contexts:
        await playwright.stop()
        raise BrowserHandoffUnavailable("The retained browser has no active context.")
    context = contexts[0]
    pages = list(context.pages)
    if not pages:
        page = await context.new_page()
    else:
        page = next(
            (candidate for candidate in pages if session.current_url and candidate.url == session.current_url),
            pages[-1],
        )
    return playwright, browser, context, page


async def _disconnect(playwright) -> None:
    try:
        await playwright.stop()
    except Exception:
        pass


async def capture_handoff_frame(session: ManualHandoffSession) -> bytes:
    playwright, _, _, page = await _connect_local_cdp(session)
    try:
        return await page.screenshot(type="png", full_page=False)
    finally:
        await _disconnect(playwright)


async def perform_handoff_action(
    session: ManualHandoffSession,
    *,
    action: str,
    x: Optional[float] = None,
    y: Optional[float] = None,
    text: Optional[str] = None,
    key: Optional[str] = None,
    delta_x: float = 0,
    delta_y: float = 0,
) -> Dict[str, Any]:
    playwright, _, _, page = await _connect_local_cdp(session)
    try:
        if action == "click":
            if x is None or y is None:
                raise BrowserHandoffError("Click actions require x and y coordinates.")
            await page.mouse.click(float(x), float(y))
        elif action == "type":
            if text is None:
                raise BrowserHandoffError("Type actions require text.")
            await page.keyboard.insert_text(text)
        elif action == "key":
            allowed_keys = {
                "Tab", "Shift+Tab", "Enter", "Escape", "Backspace", "Delete",
                "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space",
            }
            if key not in allowed_keys:
                raise BrowserHandoffError("The requested keyboard action is not allowed.")
            await page.keyboard.press(key)
        elif action == "scroll":
            await page.mouse.wheel(float(delta_x), float(delta_y))
        else:
            raise BrowserHandoffError(f"Unsupported browser handoff action: {action}")
        await page.wait_for_timeout(150)
        fingerprint = await page_fingerprint(page)
        return {
            "action": action,
            "current_url": page.url,
            "current_fingerprint": fingerprint,
            "sensitive_value_logged": False,
        }
    finally:
        await _disconnect(playwright)


async def _captcha_response_state(page) -> Dict[str, Any]:
    selectors = (
        'textarea[name="g-recaptcha-response"]',
        'textarea[name="h-captcha-response"]',
        'input[name="cf-turnstile-response"]',
        'textarea[name="cf-turnstile-response"]',
    )
    lengths = []
    for selector in selectors:
        try:
            for element in await page.query_selector_all(selector):
                value = await element.input_value()
                lengths.append({"selector": selector, "length": len(value or "")})
        except Exception:
            continue
    return {
        "responses": lengths,
        "has_completed_response": any(item["length"] >= 20 for item in lengths),
    }


async def verify_browser_handoff_completion(
    session: ManualHandoffSession,
) -> BrowserVerification:
    playwright, _, context, page = await _connect_local_cdp(session)
    try:
        fingerprint = await page_fingerprint(page)
        evidence: Dict[str, Any] = {}
        cleared = False

        if session.challenge_type == HandoffChallengeType.captcha.value:
            response_state = await _captcha_response_state(page)
            evidence.update(response_state)
            cleared = bool(response_state["has_completed_response"])
        else:
            challenge = await detect_blocking_challenge(page)
            evidence["remaining_challenge"] = challenge
            cleared = challenge is None

        storage_state = await context.storage_state()
        storage_digest = hashlib.sha256(repr(storage_state).encode("utf-8")).hexdigest()
        evidence["storage_state_hash"] = storage_digest
        evidence["verification_method"] = "browser_state"

        return BrowserVerification(
            challenge_cleared=cleared,
            provider=session.browser_provider,
            current_url=page.url,
            current_fingerprint=fingerprint,
            evidence=evidence,
        )
    finally:
        await _disconnect(playwright)


async def resume_handoff_application(
    session: ManualHandoffSession,
    *,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool,
) -> Dict[str, Any]:
    """Reconnect to the retained page and continue the certified ATS flow."""
    from app.services.ats_flow import run_ats_application_flow
    from app.services.ats_registry import detect_ats_adapter
    from app.services.form_filler_v3 import _fill_step_fields

    playwright, _, _, page = await _connect_local_cdp(session)
    log: list[Dict[str, Any]] = []
    try:
        adapter = await detect_ats_adapter(page, page.url)

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
        result = flow.as_dict()
        result["log"] = log
        result["ats_adapter"] = flow.adapter_name
        result["ats_adapter_version"] = flow.adapter_version
        result["url"] = page.url
        return result
    finally:
        await _disconnect(playwright)


async def persist_handoff_screenshot(
    session: ManualHandoffSession,
    target_path: str,
) -> str:
    data = await capture_handoff_frame(session)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(target)


def terminate_retained_browser(session: ManualHandoffSession) -> bool:
    _require_local_affinity(session)
    pid = session.browser_process_id
    if not pid:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise BrowserHandoffUnavailable("The retained browser process cannot be terminated safely.") from exc
