from __future__ import annotations

import asyncio
import json

from app.database import SessionLocal
from app.models.application import Application
from app.models.handoff import ManualHandoffSession
from app.models.submission_approval import SubmissionApproval
from app.services import browser_handoff
from app.services.ats_registry import detect_ats_adapter

APP_ID = 247
HANDOFF_ID = "48516034-2bc6-4a2a-a576-6de232ca69f6"
APPROVAL_REFERENCE = "lvsup-7hr1x7PsxKvPU79uSGcvNpn9"
EXPECTED_URL = "https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/apply"
CONFIRMATION_PHRASES = (
    "thank you for applying",
    "your application has been received",
    "application has been received",
    "application received",
    "application submitted",
    "we have received your application",
    "we've received your application",
)


def emit(status: str, **payload) -> None:
    print(json.dumps({"status": status, **payload}, indent=2, default=str), flush=True)


async def inspect_page(session: ManualHandoffSession) -> dict:
    playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
    try:
        url = str(page.url or "")
        title = await page.title()
        body = (await page.locator("body").inner_text())[:40000]
        normalized = " ".join(body.lower().split())
        matched = [phrase for phrase in CONFIRMATION_PHRASES if phrase in normalized]

        adapter = await detect_ats_adapter(page, url)
        surface = await adapter.resolve_surface(page)
        submit = await adapter.find_submit_button(surface)
        submit_visible = False
        submit_enabled = False
        submit_text = ""
        if submit is not None:
            try:
                submit_visible = bool(await submit.is_visible())
                submit_enabled = bool(await submit.is_enabled())
                submit_text = ((await submit.inner_text()) or "").strip()[:200]
            except Exception:
                pass

        validation_errors = await adapter.extract_validation_errors(surface)
        fingerprint = await browser_handoff.page_fingerprint(page)

        return {
            "current_url": url,
            "title": title,
            "current_fingerprint": fingerprint,
            "adapter": adapter.name,
            "adapter_version": adapter.version,
            "confirmation_phrases": matched,
            "confirmation_text_present": bool(matched),
            "submit_control_present": submit is not None,
            "submit_control_visible": submit_visible,
            "submit_control_enabled": submit_enabled,
            "submit_control_text": submit_text,
            "validation_error_count": len(validation_errors),
            "body_excerpt": body[:2500],
        }
    finally:
        await browser_handoff._disconnect(playwright)


def run() -> int:
    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == APP_ID).one()
        handoff = (
            db.query(ManualHandoffSession)
            .filter(
                ManualHandoffSession.public_id == HANDOFF_ID,
                ManualHandoffSession.application_id == APP_ID,
            )
            .one()
        )
        approval = (
            db.query(SubmissionApproval)
            .filter(
                SubmissionApproval.application_id == APP_ID,
                SubmissionApproval.reference == APPROVAL_REFERENCE,
            )
            .one()
        )
        metadata = dict(approval.approval_metadata or {})

        page = asyncio.run(inspect_page(handoff))

        emit(
            "MAPLE_POST_CLICK_READ_ONLY_PROBE",
            application_status=app.status,
            automation_state=app.automation_state,
            applied_at=app.applied_at,
            handoff_status=handoff.status,
            handoff_current_url=handoff.current_url,
            handoff_current_fingerprint=handoff.current_fingerprint,
            approval_status=approval.status,
            approval_consumed_at=approval.consumed_at,
            approval_action_started=bool(metadata.get("operator_submit_action_started_at")),
            approval_action_result=metadata.get("operator_submit_action_result"),
            automatic_retry_allowed=False,
            **page,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run())
