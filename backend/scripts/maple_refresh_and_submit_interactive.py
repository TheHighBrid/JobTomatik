from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

from fastapi import HTTPException

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
EMPLOYER = "Maple"
ROLE = "Client Success Associate (Bilingual, French/English)"
URL = "https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/apply"
EXPECTED_FINGERPRINT = "5d9ac574f7e196757d24ea42"
EXACT_AUTHORIZATION = f"SUBMIT {EMPLOYER} | {ROLE} | {URL}"


def emit(status: str, **payload) -> None:
    print(json.dumps({"status": status, **payload}, indent=2, default=str), flush=True)


install_handoff_task_integration()
install_operator_assisted_handoff_integration()

from app.api.handoffs import bootstrap_handoff, claim_handoff, complete_handoff
from app.api.supervised_submissions import (
    authorize_operator_final_click,
    create_operator_assisted_approval,
    submit_operator_assisted_final_action,
)
from app.schemas.handoff import HandoffClaimRequest, HandoffReadyRequest
from app.schemas.supervised_submission import (
    OperatorAssistedApprovalCreate,
    OperatorAssistedFinalSubmitRequest,
)
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
        if live_url != URL:
            raise RuntimeError(f"STOP_LIVE_URL_CHANGED actual={live_url}")
        if live_fp != EXPECTED_FINGERPRINT:
            raise RuntimeError(
                f"STOP_LIVE_FINGERPRINT_CHANGED expected={EXPECTED_FINGERPRINT} actual={live_fp}"
            )

        emit(
            "MAPLE_LIVE_FINAL_PAGE_REVERIFIED",
            url=live_url,
            fingerprint=live_fp,
            same_exact_page=True,
        )

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
        handoff_id = issued.session.public_id

        emit(
            "MAPLE_FRESH_60_MIN_HANDOFF_READY",
            handoff_public_id=handoff_id,
            expires_at=issued.session.expires_at,
            operator_preflight_ready=True,
            automated_submission_authorized=False,
            final_submit_clicked_by_jobtomatik=False,
        )

        print("\nType the exact authorization below, then press Enter:\n", flush=True)
        print(EXACT_AUTHORIZATION, flush=True)
        provided = input("\nAUTHORIZATION> ").strip()
        if provided != EXACT_AUTHORIZATION:
            emit(
                "STOP_AUTHORIZATION_MISMATCH",
                submit_clicked=False,
                automated_submission_authorized=False,
            )
            return 30

        approval_data = OperatorAssistedApprovalCreate(
            handoff_public_id=handoff_id,
            confirm_employer=EMPLOYER,
            confirm_role=ROLE,
            confirm_application_url=URL,
            confirm_operator_final_click=True,
            expires_in_minutes=20,
            notes="Owner entered the exact final-submit authorization locally after live-page reverification.",
        )
        approval = asyncio.run(
            create_operator_assisted_approval(
                APP_ID,
                approval_data,
                current_user=user,
                db=db,
            )
        )
        approval_ref = str(approval["reference"])

        authorization = asyncio.run(
            authorize_operator_final_click(
                APP_ID,
                approval_ref,
                current_user=user,
                db=db,
            )
        )
        if authorization.get("handoff_public_id") != handoff_id:
            raise RuntimeError("STOP_AUTHORIZATION_HANDOFF_MISMATCH")
        if authorization.get("automated_submission_authorized") is not False:
            raise RuntimeError("STOP_UNEXPECTED_AUTOMATED_AUTHORITY")

        emit(
            "MAPLE_ONE_FINAL_CLICK_AUTHORIZED",
            handoff_public_id=handoff_id,
            approval_reference=approval_ref,
            attempt_number=authorization.get("attempt_number"),
            worker_task_created=authorization.get("worker_task_created"),
            queue_created=authorization.get("queue_created"),
        )

        boot = asyncio.run(bootstrap_handoff(handoff_id, current_user=user, db=db))
        claimed = asyncio.run(
            claim_handoff(
                handoff_id,
                HandoffClaimRequest(resume_token=boot["resume_token"]),
                current_user=user,
                db=db,
            )
        )
        lease = claimed["lease_token"]

        print("=== EXECUTING ONE MAPLE SUBMIT CLICK ===", flush=True)
        try:
            result = asyncio.run(
                submit_operator_assisted_final_action(
                    APP_ID,
                    handoff_id,
                    OperatorAssistedFinalSubmitRequest(lease_token=lease),
                    current_user=user,
                    db=db,
                )
            )
        except HTTPException as exc:
            emit(
                "MAPLE_FINAL_ACTION_BLOCKED_OR_UNCERTAIN",
                http_status=exc.status_code,
                detail=str(exc.detail),
                automatic_retry_allowed=False,
                instruction="DO NOT RUN THIS SCRIPT AGAIN",
            )
            return 40

        print("=== MAPLE FINAL SUBMIT ACTION ===", flush=True)
        print(json.dumps(result, indent=2, default=str), flush=True)

        completion = None
        last_error = None
        for attempt in range(1, 7):
            try:
                completion = asyncio.run(
                    complete_handoff(
                        handoff_id,
                        HandoffReadyRequest(lease_token=lease),
                        current_user=user,
                        db=db,
                    )
                )
                break
            except HTTPException as exc:
                last_error = str(exc.detail)
                if exc.status_code == 409 and attempt < 6:
                    time.sleep(2)
                    continue
                break

        if completion is None:
            emit(
                "MAPLE_SUBMIT_CLICK_OCCURRED_CONFIRMATION_NOT_PROVEN",
                submission_confirmed=bool(result.get("submission_confirmed")),
                detail=last_error,
                automatic_retry_allowed=False,
                instruction="DO NOT submit again. Inspect the existing Maple page only.",
            )
            return 0

        emit(
            "MAPLE_EMPLOYER_CONFIRMATION_VERIFIED",
            handoff_public_id=handoff_id,
            handoff_status=completion.status,
            automatic_retry_allowed=False,
        )

        final_state = {}
        for _ in range(45):
            db.expire_all()
            current_app = db.query(Application).filter(Application.id == APP_ID).one()
            current_handoff = (
                db.query(ManualHandoffSession)
                .filter(ManualHandoffSession.public_id == handoff_id)
                .one()
            )
            final_state = {
                "application_status": current_app.status,
                "automation_state": current_app.automation_state,
                "applied_at": current_app.applied_at,
                "handoff_status": current_handoff.status,
            }
            if (
                current_app.automation_state in {"submitted", "confirmed"}
                or current_handoff.status == "completed"
            ):
                break
            time.sleep(2)

        print("=== JOBTOMATIK FINAL STATE ===", flush=True)
        print(
            json.dumps(
                {
                    "application_id": APP_ID,
                    **final_state,
                    "automatic_retry_allowed": False,
                },
                indent=2,
                default=str,
            ),
            flush=True,
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run())
