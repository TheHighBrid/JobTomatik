from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.shadow_runs import ShadowCampaignStartRequest, ShadowCampaignStopRequest
from app.services.full_stack_shadow import (
    ShadowCampaignError,
    create_shadow_session,
    full_stack_shadow_preflight,
    list_shadow_sessions,
    mark_shadow_dispatch_failure,
    owned_shadow_session,
    record_shadow_certification_evidence,
    request_shadow_stop,
    shadow_session_status,
)
from app.services.operations_settings import get_operations_settings
from app.services.runtime_acceptance import canary_receipt_status
from app.services.runtime_identity import runtime_identity_manifest
from app.tasks.shadow_runs import run_shadow_session_cycle


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shadow-runs", tags=["certification"])

ANDROID_QUALIFICATION_RECEIPT_MAX_AGE_SECONDS = 15 * 60


def _autopilot_enabled() -> bool:
    return bool(get_operations_settings().autopilot_enabled)


def _runtime_identity_gate() -> dict:
    identity = runtime_identity_manifest()
    required = _autopilot_enabled()
    return {
        "required": required,
        "ok": (not required) or bool(identity.get("deployment_attested")),
        "identity": identity,
    }


def _public_shadow_status(db: Session, *, session) -> dict:
    """Return operator-safe status without raw worker/provider exception text."""

    payload = shadow_session_status(db, session=session)
    payload["recent_cycles"] = [
        {
            **dict(cycle),
            "error_detail": "cycle_failed" if cycle.get("error_detail") else None,
        }
        for cycle in list(payload.get("recent_cycles") or [])
    ]
    return payload


def _android_account_qualification_required(target_evidence_type: str) -> bool:
    return (
        os.environ.get("JOBTOMATIK_RUNTIME_MODE") == "android_managed"
        and str(target_evidence_type or "") == "shadow_run_4h"
    )


def _run_account_qualification(user_id: int) -> dict:
    """Run the real qualification canary for one already-authenticated account.

    The API supplies the account id from ``get_current_user``. This function must never
    discover or guess an account from database contents. Keeping the import local also
    prevents the CLI module from becoming part of normal API startup unless the
    physical Android 4h boundary actually needs a fresh qualification.
    """

    from scripts.run_shadow_qualification_canary import (
        CANARY_TIMEOUT_SECONDS,
        run_canary,
    )

    return run_canary(
        requested_user_id=int(user_id),
        timeout_seconds=CANARY_TIMEOUT_SECONDS,
    )


def _qualification_summary(admission: dict, *, user_id: int, performed: bool) -> dict:
    receipt = dict(admission.get("receipt") or {})
    application = dict(receipt.get("application") or {})
    return {
        "required": True,
        "status": "pass",
        "performed": bool(performed),
        "reused": not bool(performed),
        "user_id": int(user_id),
        "revision": receipt.get("revision"),
        "runtime_fingerprint_sha256": receipt.get("runtime_fingerprint_sha256"),
        "application_id": application.get("application_id"),
        "certification_eligible": False,
    }


def _ensure_android_account_qualification(
    *,
    user_id: int,
    target_evidence_type: str,
) -> dict:
    """Bind Android 4h qualification to the authenticated campaign owner.

    A fresh valid receipt for the exact account/runtime is reused. Otherwise the real
    production qualification path runs once for that exact account. The public API
    never returns raw provider, broker, database, or browser exception text.
    """

    if not _android_account_qualification_required(target_evidence_type):
        return {
            "required": False,
            "status": "not_required",
            "performed": False,
            "reused": False,
            "user_id": int(user_id),
            "certification_eligible": False,
        }

    admission = canary_receipt_status(
        int(user_id),
        max_age_seconds=ANDROID_QUALIFICATION_RECEIPT_MAX_AGE_SECONDS,
    )
    if admission.get("ok"):
        return _qualification_summary(admission, user_id=int(user_id), performed=False)

    try:
        _run_account_qualification(int(user_id))
    except Exception as exc:
        logger.exception(
            "Authenticated Android qualification failed for account %s",
            int(user_id),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Authenticated account qualification did not pass",
                "reason": "account_qualification_failed",
            },
        ) from exc

    admission = canary_receipt_status(
        int(user_id),
        max_age_seconds=ANDROID_QUALIFICATION_RECEIPT_MAX_AGE_SECONDS,
    )
    if not admission.get("ok"):
        logger.error(
            "Authenticated Android qualification produced an invalid receipt for account %s: %s",
            int(user_id),
            ",".join(str(item) for item in (admission.get("blockers") or [])),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Authenticated account qualification receipt was not accepted",
                "reason": "account_qualification_receipt_invalid",
            },
        )

    receipt = dict(admission.get("receipt") or {})
    if int(receipt.get("user_id") or 0) != int(user_id):
        logger.error(
            "Authenticated Android qualification account mismatch expected=%s observed=%s",
            int(user_id),
            receipt.get("user_id"),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Authenticated account qualification receipt was not accepted",
                "reason": "account_qualification_account_mismatch",
            },
        )
    return _qualification_summary(admission, user_id=int(user_id), performed=True)


@router.get("/preflight")
def get_shadow_campaign_preflight(
    target_evidence_type: str = Query(default="shadow_run_4h"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = full_stack_shadow_preflight(
        db,
        current_user,
        target_evidence_type=target_evidence_type,
    )
    gate = _runtime_identity_gate()
    payload["runtime_identity"] = gate["identity"]
    payload.setdefault("checks", {})["runtime_identity_attested"] = gate["ok"]
    if not gate["ok"]:
        blockers = list(payload.get("blockers") or [])
        if "runtime_identity_unattested" not in blockers:
            blockers.append("runtime_identity_unattested")
        payload["blockers"] = blockers
        payload["ok"] = False
        payload["expected_start_acknowledgment"] = None
    return payload


@router.get("")
def get_shadow_campaigns(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = list_shadow_sessions(db, user_id=current_user.id, limit=limit)
    return {
        "sessions": [_public_shadow_status(db, session=session) for session in sessions],
        "runtime_identity": runtime_identity_manifest(),
        "submission_authorized": False,
        "outreach_authorized": False,
    }


@router.get("/{session_id}")
def get_shadow_campaign(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        session = owned_shadow_session(
            db,
            user_id=current_user.id,
            session_id=session_id,
        )
    except ShadowCampaignError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = _public_shadow_status(db, session=session)
    payload["runtime_identity"] = runtime_identity_manifest()
    return payload


@router.post("", status_code=status.HTTP_201_CREATED)
def start_shadow_campaign(
    payload: ShadowCampaignStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    gate = _runtime_identity_gate()
    if not gate["ok"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Shadow campaign runtime identity is not deployment-attested",
                "reason": "runtime_identity_unattested",
                "revision": gate["identity"].get("revision"),
                "role": gate["identity"].get("role"),
            },
        )

    user_id = int(current_user.id)
    # Validate the cheap mutable prerequisites and exact acknowledgment before running
    # the expensive real application-path qualification. ``create_shadow_session``
    # repeats these checks after qualification so drift remains fail-closed.
    start_preflight = full_stack_shadow_preflight(
        db,
        current_user,
        target_evidence_type=payload.target_evidence_type,
    )
    if not start_preflight.get("ok"):
        raise HTTPException(
            status_code=409,
            detail="Shadow campaign preflight blocked: "
            + ", ".join(start_preflight.get("blockers") or []),
        )
    expected = str(start_preflight.get("expected_start_acknowledgment") or "")
    if payload.acknowledgment.strip() != expected:
        raise HTTPException(
            status_code=409,
            detail=f"Exact shadow acknowledgment required: {expected}",
        )

    if _android_account_qualification_required(payload.target_evidence_type):
        # End the API session's read transaction before the physical canary opens its
        # own SQLite session and writes discovery/application evidence. This prevents
        # the authenticated request itself from becoming a hidden SQLite lock holder.
        db.rollback()

    qualification = _ensure_android_account_qualification(
        user_id=user_id,
        target_evidence_type=payload.target_evidence_type,
    )
    db.expire_all()

    try:
        session = create_shadow_session(
            db,
            user_id=user_id,
            target_evidence_type=payload.target_evidence_type,
            acknowledgment=payload.acknowledgment,
            cycle_interval_seconds=payload.cycle_interval_seconds,
        )
        db.commit()
        db.refresh(session)
    except ShadowCampaignError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active shadow campaign already exists for this account",
        ) from exc

    try:
        task = run_shadow_session_cycle.delay(session.id)
    except Exception as exc:
        logger.exception("Initial shadow campaign dispatch failed for session %s", session.id)
        try:
            mark_shadow_dispatch_failure(
                db,
                session_id=session.id,
                detail="initial_worker_dispatch_unavailable",
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist initial shadow dispatch failure")
        raise HTTPException(
            status_code=503,
            detail="Shadow campaign was retained but initial worker dispatch failed",
        ) from exc

    return {
        "session_id": session.id,
        "status": session.status,
        "celery_task_id": task.id,
        "candidate_revision": session.candidate_revision,
        "runtime_identity": gate["identity"],
        "qualification": qualification,
        "target_evidence_type": session.target_evidence_type,
        "requested_duration_seconds": int(session.requested_duration_seconds),
        "expected_end_at": _public_shadow_status(db, session=session)["expected_end_at"],
        "submission_authorized": False,
        "outreach_authorized": False,
    }


@router.post("/{session_id}/stop")
def stop_shadow_campaign(
    session_id: int,
    payload: ShadowCampaignStopRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        session = request_shadow_stop(
            db,
            user_id=current_user.id,
            session_id=session_id,
            acknowledgment=payload.acknowledgment,
        )
        db.commit()
        db.refresh(session)
    except ShadowCampaignError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    dispatch_task_id = None
    dispatch_error = None
    if session.status not in {"completed", "failed", "cancelled"}:
        try:
            task = run_shadow_session_cycle.delay(session.id)
            dispatch_task_id = task.id
        except Exception:
            logger.exception("Shadow campaign stop dispatch failed for session %s", session.id)
            dispatch_error = "worker_dispatch_unavailable"
    return {
        **_public_shadow_status(db, session=session),
        "runtime_identity": runtime_identity_manifest(),
        "dispatch_task_id": dispatch_task_id,
        "dispatch_error": dispatch_error,
    }


@router.post("/{session_id}/record-evidence", status_code=status.HTTP_201_CREATED)
def record_shadow_campaign_evidence(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        evidence, duplicate = record_shadow_certification_evidence(
            db,
            user_id=current_user.id,
            session_id=session_id,
        )
        db.commit()
        db.refresh(evidence)
    except ShadowCampaignError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "evidence_id": evidence.id,
        "evidence_key": evidence.evidence_key,
        "evidence_type": evidence.evidence_type,
        "commit_sha": evidence.commit_sha,
        "duration_seconds": evidence.duration_seconds,
        "source_reference": evidence.source_reference,
        "payload_hash": evidence.payload_hash,
        "review_status": evidence.review_status,
        "duplicate": duplicate,
        "runtime_identity": runtime_identity_manifest(),
        "submission_authorized": False,
        "outreach_authorized": False,
    }
