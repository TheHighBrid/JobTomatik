from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.tasks.shadow_runs import run_shadow_session_cycle


router = APIRouter(prefix="/shadow-runs", tags=["certification"])


@router.get("/preflight")
def get_shadow_campaign_preflight(
    target_evidence_type: str = Query(default="shadow_run_4h"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return full_stack_shadow_preflight(
        db,
        current_user,
        target_evidence_type=target_evidence_type,
    )


@router.get("")
def get_shadow_campaigns(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = list_shadow_sessions(db, user_id=current_user.id, limit=limit)
    return {
        "sessions": [shadow_session_status(db, session=session) for session in sessions],
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
    return shadow_session_status(db, session=session)


@router.post("", status_code=status.HTTP_201_CREATED)
def start_shadow_campaign(
    payload: ShadowCampaignStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        session = create_shadow_session(
            db,
            user_id=current_user.id,
            target_evidence_type=payload.target_evidence_type,
            acknowledgment=payload.acknowledgment,
            cycle_interval_seconds=payload.cycle_interval_seconds,
        )
        db.commit()
        db.refresh(session)
    except ShadowCampaignError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        task = run_shadow_session_cycle.delay(session.id)
    except Exception as exc:
        try:
            mark_shadow_dispatch_failure(
                db,
                session_id=session.id,
                detail=f"initial_dispatch:{exc}",
            )
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Shadow campaign was retained but initial worker dispatch failed",
        ) from exc

    return {
        "session_id": session.id,
        "status": session.status,
        "celery_task_id": task.id,
        "candidate_revision": session.candidate_revision,
        "target_evidence_type": session.target_evidence_type,
        "requested_duration_seconds": int(session.requested_duration_seconds),
        "expected_end_at": shadow_session_status(db, session=session)["expected_end_at"],
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
        except Exception as exc:
            # The stop flag is already durable. Periodic stall recovery will finalize
            # the session when the broker is available again.
            dispatch_error = str(exc)[:1000]
    return {
        **shadow_session_status(db, session=session),
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
        "submission_authorized": False,
        "outreach_authorized": False,
    }
