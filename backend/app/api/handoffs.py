from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.handoff import (
    HandoffActorType,
    HandoffSessionEvent,
    HandoffSessionStatus,
    ManualHandoffSession,
)
from app.models.user import User
from app.schemas.handoff import (
    HandoffBrowserActionOut,
    HandoffBrowserActionRequest,
    HandoffCancelRequest,
    HandoffClaimOut,
    HandoffClaimRequest,
    HandoffDetailOut,
    HandoffIssuedOut,
    HandoffLeaseRequest,
    HandoffReadyRequest,
    HandoffSessionOut,
)
from app.services.browser_handoff import (
    BrowserHandoffError,
    BrowserHandoffUnavailable,
    capture_handoff_frame,
    perform_handoff_action,
    verify_browser_handoff_completion,
)
from app.services.handoff_recovery import recover_handoff_lease
from app.services.handoff_session import (
    HandoffSessionConflict,
    HandoffSessionExpired,
    HandoffTokenInvalid,
    cancel_handoff_session,
    claim_handoff_session,
    decrypt_handoff_secret,
    heartbeat_handoff_session,
    mark_handoff_ready,
    verify_handoff_lease,
)
from app.tasks.handoffs import resume_handoff_session_task

router = APIRouter(prefix="/handoffs", tags=["handoffs"])


def _get_owned_session(
    db: Session,
    public_id: str,
    user_id: int,
    *,
    include_events: bool = False,
    for_update: bool = False,
) -> ManualHandoffSession:
    query = db.query(ManualHandoffSession)
    if include_events:
        query = query.options(joinedload(ManualHandoffSession.events))
    query = query.filter(
        ManualHandoffSession.public_id == public_id,
        ManualHandoffSession.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    session = query.first()
    if not session:
        raise HTTPException(status_code=404, detail="Handoff session not found")
    return session


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HandoffSessionExpired):
        return HTTPException(status_code=410, detail=str(exc))
    if isinstance(exc, HandoffTokenInvalid):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (HandoffSessionConflict, BrowserHandoffUnavailable)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, BrowserHandoffError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=List[HandoffSessionOut])
async def list_handoff_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(ManualHandoffSession)
        .filter(ManualHandoffSession.user_id == current_user.id)
        .order_by(ManualHandoffSession.created_at.desc())
        .all()
    )


@router.get("/{public_id}", response_model=HandoffDetailOut)
async def get_handoff_session(
    public_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_session(db, public_id, current_user.id, include_events=True)


@router.post("/{public_id}/bootstrap", response_model=HandoffIssuedOut)
async def bootstrap_handoff(
    public_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disclose the resume token once to the authenticated session owner."""
    session = _get_owned_session(
        db,
        public_id,
        current_user.id,
        for_update=True,
    )
    if session.status != HandoffSessionStatus.awaiting_user.value:
        raise HTTPException(status_code=409, detail="Handoff session is no longer awaiting bootstrap")
    if session.resume_token_disclosed_at is not None:
        raise HTTPException(status_code=409, detail="Resume token has already been disclosed")
    token = decrypt_handoff_secret(session.encrypted_resume_token)
    if not token:
        raise HTTPException(status_code=409, detail="Resume token cannot be recovered safely")
    session.resume_token_disclosed_at = datetime.utcnow()
    session.lock_version = (session.lock_version or 0) + 1
    db.add(HandoffSessionEvent(
        handoff_session_id=session.id,
        application_id=session.application_id,
        event_type="handoff_resume_token_disclosed",
        actor_type=HandoffActorType.user.value,
        payload={"resume_token_prefix": session.resume_token_prefix},
    ))
    db.commit()
    db.refresh(session)
    return {"session": session, "resume_token": token}


@router.post("/{public_id}/claim", response_model=HandoffClaimOut)
async def claim_handoff(
    public_id: str,
    data: HandoffClaimRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_owned_session(db, public_id, current_user.id, for_update=True)
    try:
        claimed = claim_handoff_session(
            db,
            session,
            user_id=current_user.id,
            resume_token=data.resume_token,
        )
        db.commit()
        db.refresh(session)
        return {"session": session, "lease_token": claimed.lease_token}
    except Exception as exc:
        db.rollback()
        raise _translate_error(exc)


@router.post("/{public_id}/recover", response_model=HandoffClaimOut)
async def recover_handoff(
    public_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_owned_session(db, public_id, current_user.id, for_update=True)
    try:
        recovered = recover_handoff_lease(
            db,
            session,
            user_id=current_user.id,
        )
        db.commit()
        db.refresh(session)
        return {"session": session, "lease_token": recovered.lease_token}
    except Exception as exc:
        db.rollback()
        raise _translate_error(exc)


@router.post("/{public_id}/heartbeat", response_model=HandoffSessionOut)
async def heartbeat_handoff(
    public_id: str,
    data: HandoffLeaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_owned_session(db, public_id, current_user.id, for_update=True)
    try:
        heartbeat_handoff_session(
            db,
            session,
            user_id=current_user.id,
            lease_token=data.lease_token,
        )
        db.commit()
        db.refresh(session)
        return session
    except Exception as exc:
        db.rollback()
        raise _translate_error(exc)


@router.post("/{public_id}/frame")
async def get_handoff_frame(
    public_id: str,
    data: HandoffLeaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_owned_session(db, public_id, current_user.id)
    try:
        verify_handoff_lease(
            db,
            session,
            user_id=current_user.id,
            lease_token=data.lease_token,
        )
        image = await capture_handoff_frame(session)
        return Response(content=image, media_type="image/png")
    except Exception as exc:
        db.rollback()
        raise _translate_error(exc)


@router.post("/{public_id}/actions", response_model=HandoffBrowserActionOut)
async def act_on_handoff_browser(
    public_id: str,
    data: HandoffBrowserActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_owned_session(db, public_id, current_user.id, for_update=True)
    try:
        verify_handoff_lease(
            db,
            session,
            user_id=current_user.id,
            lease_token=data.lease_token,
        )
        result = await perform_handoff_action(
            session,
            action=data.action,
            x=data.x,
            y=data.y,
            text=data.text,
            key=data.key,
            delta_x=data.delta_x,
            delta_y=data.delta_y,
        )
        session.current_url = result["current_url"]
        session.current_fingerprint = result["current_fingerprint"]
        session.lock_version = (session.lock_version or 0) + 1
        db.add(HandoffSessionEvent(
            handoff_session_id=session.id,
            application_id=session.application_id,
            event_type="handoff_browser_action",
            actor_type=HandoffActorType.user.value,
            payload={
                "action": data.action,
                "current_url": session.current_url,
                "current_fingerprint": session.current_fingerprint,
                "sensitive_value_logged": False,
            },
        ))
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise _translate_error(exc)


@router.post("/{public_id}/complete", response_model=HandoffSessionOut)
async def complete_handoff(
    public_id: str,
    data: HandoffReadyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_owned_session(db, public_id, current_user.id, for_update=True)
    try:
        verify_handoff_lease(
            db,
            session,
            user_id=current_user.id,
            lease_token=data.lease_token,
        )
        verification = await verify_browser_handoff_completion(session)
        if not verification.challenge_cleared:
            raise HandoffSessionConflict(
                "The retained browser still reports an active human-verification challenge."
            )
        session.current_url = verification.current_url
        session.current_fingerprint = verification.current_fingerprint
        session.storage_state_hash = verification.evidence.get("storage_state_hash")
        mark_handoff_ready(
            db,
            session,
            user_id=current_user.id,
            lease_token=data.lease_token,
            verification=verification.as_dict(),
        )
        db.commit()
        db.refresh(session)
        resume_handoff_session_task.delay(session.public_id)
        return session
    except Exception as exc:
        db.rollback()
        raise _translate_error(exc)


@router.post("/{public_id}/cancel", response_model=HandoffSessionOut)
async def cancel_handoff(
    public_id: str,
    data: HandoffCancelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_owned_session(db, public_id, current_user.id, for_update=True)
    try:
        cancel_handoff_session(
            db,
            session,
            user_id=current_user.id,
            reason=data.reason,
        )
        db.commit()
        db.refresh(session)
        return session
    except Exception as exc:
        db.rollback()
        raise _translate_error(exc)


@router.get("/application/{application_id}/sessions", response_model=List[HandoffSessionOut])
async def list_application_handoffs(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.query(Application).filter(
        Application.id == application_id,
        Application.user_id == current_user.id,
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return (
        db.query(ManualHandoffSession)
        .filter(ManualHandoffSession.application_id == application_id)
        .order_by(ManualHandoffSession.created_at.desc())
        .all()
    )
