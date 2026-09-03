from __future__ import annotations

import asyncio
import json
from datetime import datetime

from app.database import SessionLocal
from app.models.application import Application, ManualReviewReason, ManualReviewTask
from app.models.handoff import ManualHandoffSession
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.services import browser_handoff
from app.services.handoff_integration import install_handoff_task_integration
from app.services.operator_assisted_handoff_integration import install_operator_assisted_handoff_integration

APP_ID = 247
OLD_HANDOFF_ID = "ba3b7909-bd35-4f0b-810b-88d55c2eb2bc"
EXPECTED_URL = "https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/apply"
EXPECTED_FINGERPRINT = "5d9ac574f7e196757d24ea42"


def emit(status: str, **payload) -> None:
    print(json.dumps({"status": status, **payload}, indent=2, default=str), flush=True)


install_handoff_task_integration()
install_operator_assisted_handoff_integration()

from app.services import handoff_integration, handoff_session
from app.services.handoff_notifications import create_handoff_required_notification
from app.services.operator_assisted_submission import build_operator_assisted_preflight
from app.services.supervised_target_identity import persisted_supervised_target_metadata


async def live_page_state(session: ManualHandoffSession) -> tuple[str, str]:
    playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
    try:
        return str(page.url or ""), await browser_handoff.page_fingerprint(page)
    finally:
        await browser_handoff._disconnect(playwright)


def run() -> int:
    db = SessionLocal()
    try:
        app = (
            db.query(Application)
            .filter(Application.id == APP_ID)
            .with_for_update()
            .one()
        )
        user = db.query(User).filter(User.id == app.user_id).one()
        job = db.query(Job).filter(Job.id == app.job_id).one()

        # Refuse to refresh authority if any operator-assisted final action was
        # already authorized or started. An expiry refresh is allowed only before
        # the consequential path begins.
        approvals = (
            db.query(SubmissionApproval)
            .filter(
                SubmissionApproval.application_id == APP_ID,
                SubmissionApproval.user_id == user.id,
            )
            .all()
        )
        for approval in approvals:
            metadata = dict(approval.approval_metadata or {})
            if metadata.get("approval_source") != "authenticated_user_operator_assisted":
                continue
            if metadata.get("operator_submit_action_started_at"):
                raise RuntimeError("STOP_FINAL_ACTION_ALREADY_STARTED_NO_RETRY")
            if approval.status == "consumed":
                raise RuntimeError("STOP_APPROVAL_ALREADY_CONSUMED_NO_RETRY")
            if approval.status == "active":
                raise RuntimeError("STOP_ACTIVE_OPERATOR_APPROVAL_EXISTS")

        old = (
            db.query(ManualHandoffSession)
            .filter(
                ManualHandoffSession.public_id == OLD_HANDOFF_ID,
                ManualHandoffSession.application_id == APP_ID,
                ManualHandoffSession.user_id == user.id,
                ManualHandoffSession.challenge_type == "final_submit",
            )
            .with_for_update()
            .one()
        )

        review = (
            db.query(ManualReviewTask)
            .filter(ManualReviewTask.id == old.manual_review_id)
            .with_for_update()
            .one()
        )
        if review.reason_code != ManualReviewReason.operator_final_submit_required.value:
            raise RuntimeError("STOP_REVIEW_REASON_CHANGED")

        live_url, live_fp = asyncio.run(live_page_state(old))
        if live_url != EXPECTED_URL:
            raise RuntimeError(f"STOP_LIVE_URL_CHANGED actual={live_url}")
        if live_fp != EXPECTED_FINGERPRINT:
            raise RuntimeError(
                f"STOP_LIVE_FINGERPRINT_CHANGED expected={EXPECTED_FINGERPRINT} actual={live_fp}"
            )

        emit(
            "MAPLE_EXPIRED_HANDOFF_PAGE_REVERIFIED",
            old_handoff_public_id=OLD_HANDOFF_ID,
            live_url=live_url,
            live_fingerprint=live_fp,
            same_exact_page=True,
        )

        # Mark the old active-looking row expired using the canonical handoff
        # clock check, then replace its review. The live Chromium tab remains open.
        handoff_session._expire_if_needed(db, old, datetime.utcnow())
        if old.status != "expired":
            raise RuntimeError(f"STOP_OLD_HANDOFF_NOT_EXPIRED status={old.status}")

        replacement = handoff_integration._fresh_review_for_retry(db, review)

        endpoint = handoff_session.decrypt_handoff_secret(old.encrypted_browser_endpoint)
        if not endpoint:
            raise RuntimeError("STOP_BROWSER_ENDPOINT_UNAVAILABLE")

        issued = handoff_session.issue_handoff_session(
            db,
            app,
            replacement,
            browser_provider=old.browser_provider,
            browser_session_id=old.browser_session_id,
            browser_endpoint=endpoint,
            browser_node_id=old.browser_node_id,
            browser_process_id=old.browser_process_id,
            browser_profile_path=old.browser_profile_path,
            active_page_hint=old.active_page_hint,
            current_url=live_url,
            current_fingerprint=live_fp,
            storage_state_path=old.storage_state_path,
            storage_state_hash=old.storage_state_hash,
            screenshot_path=old.screenshot_path,
            metadata=dict(old.handoff_metadata or {}),
            ttl_minutes=60,
        )

        notification = create_handoff_required_notification(
            db,
            app,
            replacement,
            issued.session,
        )
        replacement.details = {
            **dict(replacement.details or {}),
            "handoff_public_id": issued.session.public_id,
            "handoff_status": issued.session.status,
            "handoff_expires_at": issued.session.expires_at.isoformat(),
            "browser_provider": issued.session.browser_provider,
            "handoff_notification_id": notification.id,
        }

        target = persisted_supervised_target_metadata(job)
        preflight = build_operator_assisted_preflight(
            db,
            app,
            user,
            job,
            target_metadata=target,
        )
        if not preflight.get("ready"):
            raise RuntimeError(
                "STOP_REFRESHED_PREFLIGHT_BLOCKED: "
                + ", ".join(preflight.get("blockers") or [])
            )
        if preflight.get("operator_handoff_public_id") != issued.session.public_id:
            raise RuntimeError("STOP_REFRESHED_HANDOFF_PREFLIGHT_MISMATCH")

        db.commit()

        emit(
            "MAPLE_FRESH_HANDOFF_READY_NO_SUBMIT",
            handoff_public_id=issued.session.public_id,
            manual_review_id=replacement.id,
            expires_at=issued.session.expires_at,
            current_url=issued.session.current_url,
            current_fingerprint=issued.session.current_fingerprint,
            operator_preflight_ready=True,
            automated_submission_authorized=False,
            final_submit_clicked_by_jobtomatik=False,
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run())
