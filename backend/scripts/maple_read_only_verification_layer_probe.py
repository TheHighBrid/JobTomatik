from __future__ import annotations

import asyncio
import json

from app.database import SessionLocal
from app.models.handoff import ManualHandoffSession
from app.services import browser_handoff
from app.services.browser_navigation import (
    captcha_response_state,
    challenge_page_context,
    classify_challenge_context,
    detect_blocking_challenge,
)

APP_ID = 247
HANDOFF_ID = "48516034-2bc6-4a2a-a576-6de232ca69f6"


def emit(**payload) -> None:
    print(json.dumps({"status": "MAPLE_VERIFICATION_LAYER_READ_ONLY_PROBE", **payload}, indent=2, default=str), flush=True)


async def inspect(session: ManualHandoffSession) -> dict:
    playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
    try:
        response_state = await captcha_response_state(page)
        context = await challenge_page_context(page)
        contextual = classify_challenge_context(context)
        detected = await detect_blocking_challenge(page)

        iframe_sources = await page.evaluate(
            """() => Array.from(document.querySelectorAll('iframe')).map(i => i.src || '').filter(Boolean).slice(0, 30)"""
        )
        globals_state = await page.evaluate(
            """() => ({
              grecaptcha: typeof window.grecaptcha !== 'undefined',
              hcaptcha: typeof window.hcaptcha !== 'undefined',
              turnstile: typeof window.turnstile !== 'undefined'
            })"""
        )
        alerts = await page.evaluate(
            """() => Array.from(document.querySelectorAll('[role=alert], [aria-live=assertive], .field-error, .error-message, .validation-error, [class*=error i]'))
              .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
              .map(el => (el.innerText || el.textContent || '').trim())
              .filter(Boolean)
              .slice(0, 20)"""
        )

        return {
            "current_url": str(page.url or ""),
            "captcha_response_state": response_state,
            "challenge_page_context": context,
            "contextual_challenge": contextual,
            "detected_blocking_challenge": detected,
            "verification_globals": globals_state,
            "iframe_sources": iframe_sources,
            "visible_alerts": alerts,
        }
    finally:
        await browser_handoff._disconnect(playwright)


def run() -> int:
    db = SessionLocal()
    try:
        session = (
            db.query(ManualHandoffSession)
            .filter(
                ManualHandoffSession.public_id == HANDOFF_ID,
                ManualHandoffSession.application_id == APP_ID,
            )
            .one()
        )
        result = asyncio.run(inspect(session))
        emit(**result)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run())
