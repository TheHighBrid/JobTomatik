from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.certification import CertificationEvidence, ReleaseAuthorization
from app.models.user import User
from app.schemas.certification import (
    AuthorizationRevokeRequest,
    CertificationEvidenceCreate,
    CertificationEvidenceOut,
    CertificationManifestOut,
    EvidenceReviewOut,
    EvidenceReviewRequest,
    ReleaseAuthorizationCreate,
    ReleaseAuthorizationOut,
)
from app.services.certification_scale import (
    EVIDENCE_REQUIREMENTS,
    SCOPE_REQUIREMENTS,
    active_authorization,
    authorization_payload,
    build_certification_scale_manifest,
    build_release_track,
    canonical_hash,
    current_revision,
    default_authorization_expiry,
    ensure_aware,
    evidence_is_qualifying,
    evidence_key_for,
    evidence_payload,
    utc_now,
)
from app.services.shadow_evidence_provenance import SHADOW_EVIDENCE_TYPES


router = APIRouter(prefix="/certification", tags=["certification"])


def _owned_or_system_evidence(
    db: Session,
    *,
    user_id: int,
    evidence_id: int,
) -> CertificationEvidence:
    evidence = (
        db.query(CertificationEvidence)
        .filter(
            CertificationEvidence.id == evidence_id,
            or_(
                CertificationEvidence.recorded_by_user_id == user_id,
                CertificationEvidence.recorded_by_user_id.is_(None),
            ),
        )
        .first()
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Certification evidence not found")
    return evidence


def _owned_authorization(
    db: Session,
    *,
    user_id: int,
    authorization_id: int,
) -> ReleaseAuthorization:
    authorization = (
        db.query(ReleaseAuthorization)
        .filter(
            ReleaseAuthorization.id == authorization_id,
            ReleaseAuthorization.approved_by_user_id == user_id,
        )
        .first()
    )
    if authorization is None:
        raise HTTPException(status_code=404, detail="Release authorization not found")
    return authorization


def _evidence_out(record: CertificationEvidence, *, duplicate: bool = False) -> CertificationEvidenceOut:
    return CertificationEvidenceOut(
        evidence_id=record.id,
        evidence_key=record.evidence_key,
        evidence_type=record.evidence_type,
        adapter=record.adapter,
        commit_sha=record.commit_sha,
        environment=record.environment,
        status=record.status,
        duration_seconds=record.duration_seconds,
        source_reference=record.source_reference,
        payload_hash=record.payload_hash,
        evidence_metadata=dict(record.evidence_metadata or {}),
        review_status=record.review_status,
        reviewed_by_user_id=record.reviewed_by_user_id,
        reviewed_at=ensure_aware(record.reviewed_at),
        review_reference=record.review_reference,
        expires_at=ensure_aware(record.expires_at),
        created_at=ensure_aware(record.created_at),
        duplicate=duplicate,
    )


def _validate_special_evidence(payload: CertificationEvidenceCreate) -> None:
    evidence_type = payload.evidence_type
    if evidence_type not in EVIDENCE_REQUIREMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported certification evidence type: {evidence_type}",
        )

    metadata = dict(payload.evidence_metadata or {})
    if evidence_type in SHADOW_EVIDENCE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                "Shadow-run certification evidence must be created from a qualifying "
                "full-stack shadow campaign via /api/shadow-runs/{session_id}/record-evidence"
            ),
        )

    if evidence_type == "release_checksum":
        algorithm = str(metadata.get("algorithm") or "").lower()
        digest = str(metadata.get("digest") or "").lower()
        if algorithm != "sha256" or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise HTTPException(
                status_code=422,
                detail="release_checksum evidence requires a valid SHA-256 digest",
            )

    if evidence_type == "release_artifact":
        artifact_name = str(metadata.get("artifact_name") or "").strip()
        artifact_kind = str(metadata.get("artifact_kind") or "").strip().lower()
        if not artifact_name or artifact_kind not in {"android_apk", "android_aab", "source_bundle"}:
            raise HTTPException(
                status_code=422,
                detail="release_artifact evidence requires artifact_name and a supported artifact_kind",
            )


def _expected_review_ack(record: CertificationEvidence) -> str:
    return f"VERIFY EVIDENCE {record.id} {record.commit_sha[:12]}"


def _expected_authorization_ack(scope: str, release_version: str, revision: str) -> str:
    return f"AUTHORIZE {scope.upper()} {release_version} {revision[:12]}"


@router.get("/manifest", response_model=CertificationManifestOut)
def certification_manifest(
    release_version: str = Query(default="v2.00", min_length=1, max_length=80),
    adapter: str | None = Query(default=None, max_length=80),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_certification_scale_manifest(
        db,
        user_id=current_user.id,
        release_version=release_version,
        adapter=adapter,
    )


@router.get("/evidence", response_model=list[CertificationEvidenceOut])
def list_certification_evidence(
    evidence_type: str | None = Query(default=None, max_length=80),
    adapter: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(CertificationEvidence).filter(
        or_(
            CertificationEvidence.recorded_by_user_id == current_user.id,
            CertificationEvidence.recorded_by_user_id.is_(None),
        )
    )
    if evidence_type:
        query = query.filter(CertificationEvidence.evidence_type == evidence_type)
    if adapter:
        query = query.filter(CertificationEvidence.adapter == adapter)
    rows = query.order_by(
        CertificationEvidence.created_at.desc(),
        CertificationEvidence.id.desc(),
    ).limit(limit).all()
    return [_evidence_out(row) for row in rows]


@router.post(
    "/evidence",
    response_model=CertificationEvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
def record_certification_evidence(
    payload: CertificationEvidenceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_special_evidence(payload)
    full_payload = evidence_payload(
        evidence_type=payload.evidence_type,
        adapter=payload.adapter,
        commit_sha=payload.commit_sha,
        environment=payload.environment,
        status=payload.status,
        duration_seconds=payload.duration_seconds,
        source_reference=payload.source_reference,
        evidence_metadata=dict(payload.evidence_metadata or {}),
    )
    evidence_key = evidence_key_for(full_payload, owner_user_id=current_user.id)
    payload_hash = canonical_hash(full_payload)

    existing = (
        db.query(CertificationEvidence)
        .filter(CertificationEvidence.evidence_key == evidence_key)
        .first()
    )
    if existing is not None:
        if existing.recorded_by_user_id not in {None, current_user.id}:
            raise HTTPException(status_code=409, detail="Evidence identity is already reserved")
        if existing.payload_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="Evidence identity already exists with a different payload",
            )
        return _evidence_out(existing, duplicate=True)

    record = CertificationEvidence(
        evidence_key=evidence_key,
        evidence_type=payload.evidence_type,
        adapter=payload.adapter,
        commit_sha=payload.commit_sha,
        environment=payload.environment,
        status=payload.status,
        duration_seconds=payload.duration_seconds,
        source_reference=payload.source_reference,
        payload_hash=payload_hash,
        evidence_metadata=dict(payload.evidence_metadata or {}),
        recorded_by_user_id=current_user.id,
        review_status="unreviewed",
        expires_at=ensure_aware(payload.expires_at),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _evidence_out(record)


@router.post("/evidence/{evidence_id}/verify", response_model=EvidenceReviewOut)
def verify_certification_evidence(
    evidence_id: int,
    payload: EvidenceReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = _owned_or_system_evidence(db, user_id=current_user.id, evidence_id=evidence_id)
    if record.recorded_by_user_id is None:
        raise HTTPException(
            status_code=403,
            detail="System-scoped certification evidence cannot be user-verified",
        )
    expected = _expected_review_ack(record)
    if payload.acknowledgment != expected:
        raise HTTPException(
            status_code=422,
            detail=f"Acknowledgment must exactly match: {expected}",
        )

    # Integrity and full-stack shadow provenance must be established before review
    # state can become verified. The same provenance is checked again by the release
    # evaluator, so later session/report drift fails closed after verification too.
    qualifying_before_review, reasons_before_review = evidence_is_qualifying(
        record,
        revision=record.commit_sha,
        db=db,
        user_id=current_user.id,
    )
    integrity_reasons = [
        reason for reason in reasons_before_review if reason != "not_independently_verified"
    ]
    if integrity_reasons:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Evidence cannot be verified because integrity checks failed",
                "reasons": integrity_reasons,
            },
        )

    now = utc_now()
    record.review_status = "verified"
    record.reviewed_by_user_id = current_user.id
    record.reviewed_at = now
    record.review_reference = payload.review_reference
    db.commit()
    db.refresh(record)

    current = current_revision()
    qualifying, reasons = evidence_is_qualifying(
        record,
        revision=current,
        db=db,
        user_id=current_user.id,
    )
    return EvidenceReviewOut(
        evidence_id=record.id,
        review_status=record.review_status,
        reviewed_by_user_id=current_user.id,
        reviewed_at=now,
        review_reference=payload.review_reference,
        qualifying_for_current_head=qualifying,
        qualifying_reasons=reasons,
    )


@router.post(
    "/authorizations",
    response_model=ReleaseAuthorizationOut,
    status_code=status.HTTP_201_CREATED,
)
def authorize_release_track(
    payload: ReleaseAuthorizationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.scope not in SCOPE_REQUIREMENTS:
        raise HTTPException(status_code=422, detail="Unsupported release-authorization scope")

    revision = current_revision()
    if revision == "unknown":
        raise HTTPException(
            status_code=409,
            detail="Current runtime revision is unknown; authorization fails closed",
        )
    if payload.commit_sha != revision:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Authorization must bind to the exact current revision",
                "current_revision": revision,
                "requested_revision": payload.commit_sha,
            },
        )

    expected_ack = _expected_authorization_ack(
        payload.scope,
        payload.release_version,
        revision,
    )
    if payload.acknowledgment != expected_ack:
        raise HTTPException(
            status_code=422,
            detail=f"Acknowledgment must exactly match: {expected_ack}",
        )

    track = build_release_track(
        db,
        user_id=current_user.id,
        scope=payload.scope,
        release_version=payload.release_version,
        revision=revision,
    )
    if not track["prerequisites_ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Release prerequisites are not fully verified",
                "blockers": track["blockers"],
            },
        )

    existing = active_authorization(
        db,
        user_id=current_user.id,
        scope=payload.scope,
        release_version=payload.release_version,
        revision=revision,
    )
    if existing is not None:
        return ReleaseAuthorizationOut(
            authorization_id=existing.id,
            scope=existing.scope,
            release_version=existing.release_version,
            commit_sha=existing.commit_sha,
            approval_reference=existing.approval_reference,
            status=existing.status,
            approved_by_user_id=existing.approved_by_user_id,
            approved_at=ensure_aware(existing.approved_at),
            expires_at=ensure_aware(existing.expires_at),
            runtime_enablement_changed=False,
        )

    now = utc_now()
    expires_at = ensure_aware(payload.expires_at) or default_authorization_expiry(
        payload.scope,
        now=now,
    )
    if expires_at <= now:
        raise HTTPException(status_code=422, detail="Authorization expiry must be in the future")

    authorization_body = authorization_payload(
        scope=payload.scope,
        release_version=payload.release_version,
        commit_sha=revision,
        approved_by_user_id=current_user.id,
        approval_reference=payload.approval_reference,
        expires_at=expires_at,
    )
    authorization = ReleaseAuthorization(
        scope=payload.scope,
        release_version=payload.release_version,
        commit_sha=revision,
        approval_reference=payload.approval_reference,
        payload_hash=canonical_hash(authorization_body),
        status="approved",
        approved_by_user_id=current_user.id,
        approved_at=now,
        expires_at=expires_at,
        authorization_metadata={
            "version": "phase10-certification-v1",
            "acknowledgment": payload.acknowledgment,
            "prerequisites_snapshot_hash": canonical_hash(track["evidence"]),
            "runtime_enablement_changed": False,
        },
    )
    db.add(authorization)
    db.commit()
    db.refresh(authorization)
    return ReleaseAuthorizationOut(
        authorization_id=authorization.id,
        scope=authorization.scope,
        release_version=authorization.release_version,
        commit_sha=authorization.commit_sha,
        approval_reference=authorization.approval_reference,
        status=authorization.status,
        approved_by_user_id=authorization.approved_by_user_id,
        approved_at=ensure_aware(authorization.approved_at),
        expires_at=ensure_aware(authorization.expires_at),
        runtime_enablement_changed=False,
    )


@router.post("/authorizations/{authorization_id}/revoke", response_model=ReleaseAuthorizationOut)
def revoke_release_authorization(
    authorization_id: int,
    payload: AuthorizationRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    authorization = _owned_authorization(
        db,
        user_id=current_user.id,
        authorization_id=authorization_id,
    )
    expected = f"REVOKE AUTHORIZATION {authorization.id}"
    if payload.acknowledgment != expected:
        raise HTTPException(
            status_code=422,
            detail=f"Acknowledgment must exactly match: {expected}",
        )
    if authorization.status != "revoked":
        authorization.status = "revoked"
        authorization.revoked_at = utc_now()
        metadata = dict(authorization.authorization_metadata or {})
        metadata["revoked_reason"] = payload.reason
        metadata["revoked_by_user_id"] = current_user.id
        metadata["runtime_enablement_changed"] = False
        authorization.authorization_metadata = metadata
        db.commit()
        db.refresh(authorization)

    return ReleaseAuthorizationOut(
        authorization_id=authorization.id,
        scope=authorization.scope,
        release_version=authorization.release_version,
        commit_sha=authorization.commit_sha,
        approval_reference=authorization.approval_reference,
        status=authorization.status,
        approved_by_user_id=authorization.approved_by_user_id,
        approved_at=ensure_aware(authorization.approved_at),
        expires_at=ensure_aware(authorization.expires_at),
        runtime_enablement_changed=False,
    )
