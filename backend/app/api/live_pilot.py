from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.live_pilot import LivePilotAuthorization
from app.models.user import User
from app.services.day39_live_authorization import (
    create_live_pilot_authorization,
    live_pilot_authorization_integrity_ok,
    revoke_live_pilot_authorization,
)
from app.services.day39_live_runtime import build_canonical_day39_live_context
from app.services.day39_live_window import (
    DAY39_LIVE_ADAPTER,
    DAY39_LIVE_ADAPTER_VERSION,
    DAY39_LIVE_MAX_ATTEMPTS,
    DAY39_LIVE_MAX_WINDOW_SECONDS,
    build_day39_live_window_readiness,
    expected_live_window_acknowledgment,
)


router = APIRouter(prefix="/live-pilot", tags=["live-pilot"])


class LivePilotAuthorizeRequest(BaseModel):
    approval_reference: str = Field(min_length=1, max_length=255)
    max_submission_attempts: int = Field(default=2, ge=1, le=DAY39_LIVE_MAX_ATTEMPTS)
    window_minutes: int = Field(default=360, ge=5, le=DAY39_LIVE_MAX_WINDOW_SECONDS // 60)
    acknowledgment: str = Field(min_length=1, max_length=300)


class LivePilotRevokeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_authorization(record: LivePilotAuthorization | None) -> dict | None:
    if record is None:
        return None
    return {
        "id": int(record.id),
        "adapter": str(record.adapter),
        "adapter_version": str(record.adapter_version),
        "commit_sha": str(record.commit_sha),
        "approval_reference": str(record.approval_reference),
        "status": str(record.status),
        "starts_at": record.starts_at.isoformat() if record.starts_at else None,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "max_submission_attempts": int(record.max_submission_attempts or 0),
        "reserved_submission_attempts": int(record.reserved_submission_attempts or 0),
        "approved_at": record.approved_at.isoformat() if record.approved_at else None,
        "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
        "integrity_ok": live_pilot_authorization_integrity_ok(record),
    }


def _owner_request(
    *,
    context: dict,
    approval_reference: str,
    attempt_cap: int,
    window_minutes: int,
    acknowledgment: str,
    now: datetime,
) -> dict:
    revision = str(context.get("promotion", {}).get("release_candidate_revision") or "")
    return {
        "approved": True,
        "approval_reference": " ".join(approval_reference.strip().split()),
        "approved_for_commit": revision,
        "adapter": DAY39_LIVE_ADAPTER,
        "adapter_version": DAY39_LIVE_ADAPTER_VERSION,
        "max_submission_attempts": int(attempt_cap),
        "starts_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=int(window_minutes))).isoformat(),
        "acknowledgment": acknowledgment,
    }


@router.get("/preflight")
def live_pilot_preflight(
    max_submission_attempts: int = Query(default=2, ge=1, le=DAY39_LIVE_MAX_ATTEMPTS),
    window_minutes: int = Query(default=360, ge=5, le=DAY39_LIVE_MAX_WINDOW_SECONDS // 60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return exact owner text and canonical readiness without persisting authority."""

    current = _now()
    context = build_canonical_day39_live_context(db, current_user, now=current)
    revision = str(context.get("promotion", {}).get("release_candidate_revision") or "")
    expected = expected_live_window_acknowledgment(
        revision=revision,
        attempt_cap=max_submission_attempts,
    )
    owner = _owner_request(
        context=context,
        approval_reference="preflight-only-not-authority",
        attempt_cap=max_submission_attempts,
        window_minutes=window_minutes,
        acknowledgment=expected,
        now=current,
    )
    report = build_day39_live_window_readiness(
        promotion=context["promotion"],
        adapter_state=context["adapter_state"],
        runtime_safety=context["runtime_safety"],
        policy_state=context["policy_state"],
        owner_request=owner,
        now=current,
    )
    return {
        "expected_acknowledgment": expected or None,
        "requested_attempt_cap": max_submission_attempts,
        "window_minutes": window_minutes,
        "authorization_eligible_if_owner_confirms": report.get("authorization_eligible") is True,
        "blockers": report.get("blockers") or [],
        "release_candidate_revision": report.get("release_candidate_revision"),
        "runtime_safety": context["runtime_safety"],
        "policy_state": context["policy_state"],
        "adapter": {
            "name": context["adapter_state"].get("name"),
            "version": context["adapter_state"].get("version"),
            "maturity": context["adapter_state"].get("maturity"),
            "autonomous_submission_allowed": context["adapter_state"].get(
                "autonomous_submission_allowed"
            ),
        },
        "authority_persisted": False,
        "real_submission_enabled": False,
    }


@router.post("/authorize")
def authorize_live_pilot(
    payload: LivePilotAuthorizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist a bounded owner authorization; never toggle real-submit runtime state."""

    current = _now()
    context = build_canonical_day39_live_context(db, current_user, now=current)
    owner = _owner_request(
        context=context,
        approval_reference=payload.approval_reference,
        attempt_cap=payload.max_submission_attempts,
        window_minutes=payload.window_minutes,
        acknowledgment=payload.acknowledgment,
        now=current,
    )
    try:
        record, report = create_live_pilot_authorization(
            db,
            approved_by_user_id=int(current_user.id),
            promotion=context["promotion"],
            adapter_state=context["adapter_state"],
            runtime_safety=context["runtime_safety"],
            policy_state=context["policy_state"],
            owner_request=owner,
            now=current,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="live_pilot_authorization_conflict") from exc

    if record is None:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "live_pilot_authorization_blocked",
                "blockers": report.get("blockers") or [],
                "next_action": report.get("next_action"),
            },
        )

    db.commit()
    db.refresh(record)
    return {
        "authorization": _serialize_authorization(record),
        "readiness": report,
        "runtime_enablement_changed": False,
        "real_submission_enabled": False,
        "followup_send_authorized": False,
    }


@router.get("/status")
def live_pilot_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current = _now()
    rows = (
        db.query(LivePilotAuthorization)
        .filter(LivePilotAuthorization.approved_by_user_id == int(current_user.id))
        .order_by(LivePilotAuthorization.approved_at.desc(), LivePilotAuthorization.id.desc())
        .limit(10)
        .all()
    )
    active = next(
        (
            row
            for row in rows
            if row.status == "approved"
            and row.revoked_at is None
            and row.starts_at is not None
            and row.expires_at is not None
            and row.starts_at <= current
            and row.expires_at > current
            and live_pilot_authorization_integrity_ok(row)
        ),
        None,
    )
    return {
        "active": _serialize_authorization(active),
        "recent": [_serialize_authorization(row) for row in rows],
    }


@router.post("/{authorization_id}/revoke")
def revoke_live_pilot(
    authorization_id: int,
    payload: LivePilotRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = (
        db.query(LivePilotAuthorization)
        .filter(
            LivePilotAuthorization.id == int(authorization_id),
            LivePilotAuthorization.approved_by_user_id == int(current_user.id),
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="live_pilot_authorization_not_found")
    if record.status != "revoked":
        revoke_live_pilot_authorization(
            db,
            authorization=record,
            reason=payload.reason,
            revoked_by_user_id=int(current_user.id),
            now=_now(),
        )
        db.commit()
        db.refresh(record)
    return {
        "authorization": _serialize_authorization(record),
        "reserved_attempts_reclaimed": False,
    }
