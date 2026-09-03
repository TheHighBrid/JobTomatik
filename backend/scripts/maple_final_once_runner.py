from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

from fastapi import HTTPException

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application, ManualReviewReason
from app.models.handoff import ManualHandoffSession
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.services import browser_handoff
from app.services.handoff_integration import _attach_handoff_session, install_handoff_task_integration
from app.services.operator_assisted_handoff_integration import install_operator_assisted_handoff_integration

EXPECTED_REPO_SHA = "33da03e0dcf381ba5008d066dccfa5a4eae43999"
APP_ID = 247
TASK_ID = "38ff69da-5874-404f-9f74-533ac4aa2382"
EMPLOYER = "Maple"
ROLE = "Client Success Associate (Bilingual, French/English)"
URL = "https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/apply"
EXPECTED_FINGERPRINT = "5d9ac574f7e196757d24ea42"


def out(status: str, **payload) -> None:
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
                raise RuntimeError(
                    "STOP_FINAL_ACTION_ALREADY_STARTED: do not retry; inspect employer page only"
                )
            if approval.status == "consumed":
                raise RuntimeError(
                    "STOP_APPROVAL_ALREADY_CONSUMED: do not issue a second final click"
                )
            if approval.status == "active":
                raise RuntimeError(
                    "STOP_ACTIVE_OPERATOR_APPROVAL_EXISTS: resolve it before continuing"
                )

        task = celery_app.AsyncResult(TASK_ID)
        if task.state != "SUCCESS" or not isinstance(task.result, dict):
            raise RuntimeError("Original Maple preparation result is unavailable")
        original = dict(task.result)
        if original.get("ready_to_submit") is not True:
            raise RuntimeError("Original Maple preparation was not ready_to_submit")
        if original.get("final_submit_clicked_by_jobtomatik") is not False:
            raise RuntimeError("Historical final-click evidence is unsafe")
        if not isinstance(original.get("handoff_snapshot"), dict):
            raise RuntimeError("Original retained browser snapshot is unavailable")

        latest = (
            db.query(ManualHandoffSession)
            .filter(
                ManualHandoffSession.application_id == APP_ID,
                ManualHandoffSession.challenge_type == "final_submit",
            )
            .order_by(ManualHandoffSession.id.desc())
            .first()
        )
        if latest is None:
            raise RuntimeError("No Maple final-submit handoff exists")

        live_url, live_fp = asyncio.run(live_page_state(latest))
        if live_url != URL:
            raise RuntimeError(f"STOP_LIVE_URL_CHANGED: {live_url}")
        if live_fp != EXPECTED_FINGERPRINT:
            raise RuntimeError(
                f"STOP_LIVE_FINGERPRINT_CHANGED expected={EXPECTED_FINGERPRINT} actual={live_fp}"
            )
        out("LIVE_MAPLE_PAGE_REVERIFIED", url=live_url, fingerprint=live_fp)

        # Reissue from the already-certified retained snapshot. The canonical handoff
        # integration expires terminal/stale sessions and creates a fresh review/session.
        _attach_handoff_session(
            db,
            app,
            original,
            ManualReviewReason.operator_final_submit_required,
        )
        db.flush()

        now = datetime.utcnow()
        fresh = (
            db.query(ManualHandoffSession)
            .filter(
                ManualHandoffSession.application_id == APP_ID,
                ManualHandoffSession.challenge_type == "final_submit",
                ManualHandoffSession.status == "awaiting_user",
            )
            .order_by(ManualHandoffSession.id.desc())
            .all()
        )
        fresh = [session for session in fresh if session.expires_at > now]
        if len(fresh) != 1:
            raise RuntimeError(
                f"Expected exactly one fresh final-submit handoff, found {len(fresh)}"
            )
        handoff = fresh[0]
        if handoff.current_url != URL or handoff.current_fingerprint != EXPECTED_FINGERPRINT:
            raise RuntimeError("Fresh handoff target binding changed")
        db.commit()
        handoff_id = handoff.public_id
        out(
            "FRESH_FINAL_HANDOFF_CREATED",
            handoff_public_id=handoff_id,
            expires_at=handoff.expires_at,
            url=handoff.current_url,
            fingerprint=handoff.current_fingerprint,
        )

        approval_data = OperatorAssistedApprovalCreate(
            handoff_public_id=handoff_id,
            confirm_employer=EMPLOYER,
            confirm_role=ROLE,
            confirm_application_url=URL,
            confirm_operator_final_click=True,
            expires_in_minutes=20,
            notes=(
                "Owner explicitly authorized: SUBMIT Maple | "
                "Client Success Associate (Bilingual, French/English) | " + URL
            ),
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
        out(
            "OWNER_APPROVAL_BOUND",
            approval_reference=approval_ref,
            handoff_public_id=handoff_id,
        )

        authorization = asyncio.run(
            authorize_operator_final_click(
                APP_ID,
                approval_ref,
                current_user=user,
                db=db,
            )
        )
        if authorization.get("handoff_public_id") != handoff_id:
            raise RuntimeError("Authorization/handoff mismatch")
        if authorization.get("automated_submission_authorized") is not False:
            raise RuntimeError("Unexpected automated submission authority")
        out(
            "ONE_FINAL_CLICK_AUTHORIZED",
            handoff_public_id=handoff_id,
            attempt_number=authorization.get("attempt_number"),
            worker_task_created=authorization.get("worker_task_created"),
            queue_created=authorization.get("queue_created"),
        )

        boot = asyncio.run(
            bootstrap_handoff(handoff_id, current_user=user, db=db)
        )
        claimed = asyncio.run(
            claim_handoff(
                handoff_id,
                HandoffClaimRequest(resume_token=boot["resume_token"]),
                current_user=user,
                db=db,
            )
        )
        lease = claimed["lease_token"]

        print("=== EXECUTING THE SINGLE AUTHORIZED MAPLE SUBMIT CLICK ===", flush=True)
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
            out(
                "FINAL_ACTION_BLOCKED_OR_UNCERTAIN",
                http_status=exc.status_code,
                detail=str(exc.detail),
                automatic_retry_allowed=False,
                instruction="DO NOT RUN THIS RUNNER AGAIN",
            )
            return 40

        print("=== MAPLE FINAL SUBMIT ACTION ===", flush=True)
        print(json.dumps(result, indent=2, default=str), flush=True)

        if result.get("submission_confirmed") is not True:
            out(
                "SUBMIT_CLICK_OCCURRED_CONFIRMATION_NOT_PROVEN",
                automatic_retry_allowed=False,
                instruction="DO NOT submit again. Inspect the existing Maple page only.",
            )
            return 0

        completion = None
        last_error = None
        for attempt in range(1, 6):
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
                if exc.status_code == 409 and attempt < 5:
                    time.sleep(2)
                    continue
                break

        if completion is None:
            out(
                "SUBMISSION_CONFIRMED_BUT_PIPELINE_FINALIZATION_PENDING",
                detail=last_error,
                automatic_retry_allowed=False,
            )
            return 0

        out(
            "EMPLOYER_CONFIRMATION_VERIFIED",
            handoff_public_id=handoff_id,
            handoff_status=completion.status,
            automatic_retry_allowed=False,
        )

        final_state = {}
        for _ in range(40):
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
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run())
