"""Native display input relayed only from the authenticated owner handoff.

Playwright still owns and verifies the browser. X11 supplies the owner's pointer
events, never a CAPTCHA solver, token injection, or an automatic challenge loop.
"""

from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path

from app.services.operator_assisted_live_pilot_hardening import _trusted_provider_iframe


class OwnerBrowserInputUnavailable(ValueError):
    pass


async def _xdotool(*args: str) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            "xdotool", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise OwnerBrowserInputUnavailable("The owner browser display did not respond.")
    except OSError as exc:
        raise OwnerBrowserInputUnavailable("The owner browser display is unavailable.") from exc
    if process.returncode:
        raise OwnerBrowserInputUnavailable("The owner browser window is unavailable.")
    return stdout.decode().strip()


async def require_owner_window(session) -> str:
    """Reject headless, external, replaced and ambiguous browser processes."""
    if os.getenv("HANDOFF_NATIVE_INPUT_ENABLED", "").lower() != "true" or not os.getenv("DISPLAY"):
        raise OwnerBrowserInputUnavailable("An interactive owner browser is not configured.")
    pid = int(session.browser_process_id or 0)
    if session.browser_provider != "local_cdp" or pid <= 1 or not session.browser_profile_path:
        raise OwnerBrowserInputUnavailable("The retained browser is not owned by this OneHost display.")
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
    except OSError as exc:
        raise OwnerBrowserInputUnavailable("The retained browser process has stopped. Preserve its evidence.") from exc
    if (
        f"--user-data-dir={session.browser_profile_path}" not in args
        or any(arg.startswith("--headless") for arg in args)
    ):
        raise OwnerBrowserInputUnavailable("The retained process is headless or its profile identity changed.")
    windows = (await _xdotool("search", "--onlyvisible", "--pid", str(pid))).splitlines()
    if len(windows) != 1 or not windows[0].isdigit():
        raise OwnerBrowserInputUnavailable("The exact owner browser window cannot be selected safely.")
    return windows[0]


async def click_owner_viewport(page, session, *, x: float, y: float) -> None:
    """Translate one owner pointer event from screenshot CSS pixels into X11."""
    window_id = await require_owner_window(session)
    await page.bring_to_front()
    geometry = await page.evaluate("""() => ({
      x: window.screenX, y: window.screenY, width: window.outerWidth,
      height: window.outerHeight, viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight, scale: window.devicePixelRatio
    })""")
    if not all(math.isfinite(float(value)) for value in (x, y)):
        raise OwnerBrowserInputUnavailable("Invalid owner pointer coordinates.")
    if not (0 <= x < geometry["viewportWidth"] and 0 <= y < geometry["viewportHeight"]):
        raise OwnerBrowserInputUnavailable("The pointer is outside the retained browser viewport.")
    values = dict(line.split("=", 1) for line in (await _xdotool("getwindowgeometry", "--shell", window_id)).splitlines() if "=" in line)
    expected = {"X": geometry["x"], "Y": geometry["y"], "WIDTH": geometry["width"], "HEIGHT": geometry["height"]}
    if geometry["scale"] != 1 or any(abs(int(values.get(key, -10000)) - value) > 2 for key, value in expected.items()):
        raise OwnerBrowserInputUnavailable("The owner display geometry changed. Refresh the browser view.")
    content_y = geometry["y"] + geometry["height"] - geometry["viewportHeight"]
    await _xdotool("windowfocus", "--sync", window_id)
    await _xdotool("mousemove", "--sync", str(round(geometry["x"] + x)), str(round(content_y + y)), "click", "1")


async def click_owner_verification(page, session, *, x: float, y: float) -> None:
    """Only the owner may point inside a genuine verification provider iframe."""
    source = await page.evaluate("""({x, y}) => {
      const element = document.elementFromPoint(x, y);
      return element?.tagName === 'IFRAME' ? element.src : '';
    }""", {"x": x, "y": y})
    if not (
        _trusted_provider_iframe(source, domains=("hcaptcha.com",))
        or _trusted_provider_iframe(source, domains=("google.com", "recaptcha.net"), path_marker="recaptcha")
        or _trusted_provider_iframe(source, domains=("challenges.cloudflare.com",))
    ):
        raise OwnerBrowserInputUnavailable("Only verification widgets are interactive here. Answers and Submit remain locked.")
    await click_owner_viewport(page, session, x=x, y=y)


async def click_owner_submit(page, session, control) -> None:
    """Activate the verified Submit control once after its durable API checkpoint."""
    await control.scroll_into_view_if_needed()
    box = await control.bounding_box()
    if not box:
        raise OwnerBrowserInputUnavailable("The exact Submit control is not visible.")
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    unobscured = await control.evaluate(
        "(element, point) => element.contains(document.elementFromPoint(point.x, point.y))",
        {"x": x, "y": y},
    )
    if not unobscured:
        raise OwnerBrowserInputUnavailable("The Submit control is covered. Complete the visible verification first.")
    await click_owner_viewport(page, session, x=x, y=y)


async def owner_handoff_capabilities(session) -> dict:
    from app.services import browser_handoff
    from app.services.operator_assisted_live_pilot_hardening import passive_verification_state

    playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
    try:
        browser_handoff._require_verified_session_target(await browser_handoff._verify_session_target(page, session))
        state = await passive_verification_state(page)
        native_ready, reason = False, None
        try:
            await require_owner_window(session)
            native_ready = True
        except OwnerBrowserInputUnavailable as exc:
            reason = str(exc)
        needs_native = bool(state.get("manual_browser_required"))
        reconcile = bool((session.handoff_metadata or {}).get("confirmation_reconciliation_required"))
        return {
            "browser_connected": True,
            "owner_pointer_enabled": native_ready,
            "manual_verification_required": needs_native,
            "submit_available": (native_ready or not needs_native) and not reconcile,
            "submit_action": "operator_native_submit" if native_ready else "operator_submit",
            "blocked_reason": "Review the retained outcome before any new submission." if reconcile else (reason if needs_native and not native_ready else None),
        }
    finally:
        await browser_handoff._disconnect(playwright)
