"""Fail-closed operator boundary for current owner-selected Lever Phase B work.

This module wraps the existing current-material services with protections that must
hold for every mutating operator surface:

1. an application with any durable active live submission attempt is quarantined
   from further material mutation or retry preparation;
2. a material review decision is bound to the exact bundle the owner inspected;
3. an already-approved exact bundle cannot be approved twice.

Read-only inspection is intentionally broader than mutation eligibility. Frozen
materials remain inspectable after execution begins or an attempt becomes uncertain,
without reopening preparation, review, approval, or submission authority.

The wrapper never issues submission approval, queues work, opens a browser, changes
runtime flags, or submits an application.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.submission_integrity import (
    ACTIVE_SUBMISSION_ATTEMPT_STATUSES,
    SubmissionAttempt,
)
from app.models.user import User
from app.services import lever_phase_b_current_materials as base
from app.services import lever_phase_b_current_materials_v5 as v5
from app.services.application_state import normalize_state
from app.services.lever_phase_b_current_intake import INTAKE_SOURCE
from app.services.lever_phase_b_runtime import canonical_lever_application_url
from app.services.supervised_target_identity import persisted_supervised_target_metadata


QUARANTINE_BLOCKER = "submission_attempt_active_no_material_mutation"


def _owned_current_application(
    db: Session,
    user: User,
    application_id: int,
    *,
    lock: bool,
) -> tuple[Application, Job]:
    query = db.query(Application).filter(
        Application.id == int(application_id),
        Application.user_id == user.id,
    )
    if lock:
        query = query.with_for_update()
    application = query.first()
    if application is None:
        raise base.LeverPhaseBReviewedMaterialsError(
            "Current Lever application was not found"
        )

    job = db.query(Job).filter(Job.id == application.job_id).first()
    if job is None:
        raise base.LeverPhaseBReviewedMaterialsError(
            "Current Lever application job is missing"
        )
    if str((job.raw_data or {}).get("selection_source") or "") != INTAKE_SOURCE:
        raise base.LeverPhaseBReviewedMaterialsError(
            "Application is not a current owner-selected Lever Phase B target"
        )
    return application, job


def _lock_and_assert_mutation_allowed(
    db: Session,
    user: User,
    application_id: int,
) -> Application:
    application, _job = _owned_current_application(
        db,
        user,
        application_id,
        lock=True,
    )

    active_attempt = (
        db.query(SubmissionAttempt.id, SubmissionAttempt.status)
        .filter(
            SubmissionAttempt.application_id == application.id,
            SubmissionAttempt.status.in_(ACTIVE_SUBMISSION_ATTEMPT_STATUSES),
        )
        .order_by(SubmissionAttempt.id.desc())
        .first()
    )
    if active_attempt is not None:
        raise base.LeverPhaseBReviewedMaterialsError(
            "Current Lever application is quarantined because a live submission "
            f"attempt is {active_attempt.status}; material mutation is blocked until "
            "the attempt reaches an independently reconciled terminal state"
        )
    return application


def prepare_current_lever_operator_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
) -> Dict[str, Any]:
    """Prepare current v5 materials only when no active attempt exists."""

    _lock_and_assert_mutation_allowed(db, user, application_id)
    return v5.prepare_current_lever_materials(
        db,
        user,
        application_id=application_id,
    )


def show_current_lever_operator_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
) -> Dict[str, Any]:
    """Inspect the frozen latest bundle without requiring a mutable local state."""

    application, job = _owned_current_application(
        db,
        user,
        application_id,
        lock=False,
    )
    target = persisted_supervised_target_metadata(job)
    if target.get("verified") is not True or target.get("blockers"):
        raise base.LeverPhaseBReviewedMaterialsError(
            "Current Lever application exact target identity is not verified"
        )
    application_url = canonical_lever_application_url(
        str(target.get("canonical_application_url") or job.url or "")
    )

    materials: Dict[str, Any] = {}
    for material_type in base.MATERIAL_TYPES:
        material = base._latest_material(db, application.id, material_type)
        if material is None:
            materials[material_type] = None
            continue
        snapshot = material.source_snapshot or {}
        materials[material_type] = {
            "id": material.id,
            "version": material.version,
            "status": material.status,
            "content": material.content,
            "warnings": list(material.warnings or []),
            "claims": list(material.claims or []),
            "preparation": dict(snapshot.get("lever_phase_b_preparation") or {}),
            "user_review": dict(snapshot.get("user_review") or {}),
        }

    return {
        "application_id": application.id,
        "job_id": job.id,
        "employer": str(job.company or "").strip(),
        "role": str(job.title or "").strip(),
        "application_url": application_url,
        "automation_state": normalize_state(application.automation_state),
        "open_review_count": base._open_review_count(db, application.id),
        "posting_sha256": (job.raw_data or {}).get("lever_official_posting_sha256"),
        "materials": materials,
        "read_only": True,
    }


def _required_bundle_mapping(
    value: Optional[Mapping[str, int]],
    field: str,
) -> Dict[str, int]:
    mapping = {str(key): int(item) for key, item in dict(value or {}).items()}
    expected_keys = set(base.MATERIAL_TYPES)
    if set(mapping) != expected_keys:
        raise base.LeverPhaseBReviewedMaterialsError(
            f"MATERIAL_BUNDLE_STALE {field} must bind both latest material types"
        )
    return mapping


def review_current_lever_operator_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
    approved: bool,
    notes: Optional[str],
    material_ids: Optional[Mapping[str, int]],
    material_versions: Optional[Mapping[str, int]],
    posting_sha256: Optional[str],
    evidence_digest: Optional[str],
) -> Dict[str, Any]:
    """Review only the exact latest bundle the owner was shown.

    The application row remains locked from the active-attempt check through the
    final review call, so neither a concurrent prepare path nor a newly reserved
    submission attempt can coexist with a material mutation.
    """

    application = _lock_and_assert_mutation_allowed(db, user, application_id)
    expected_ids = _required_bundle_mapping(material_ids, "material_ids")
    expected_versions = _required_bundle_mapping(material_versions, "material_versions")
    expected_posting = str(posting_sha256 or "").strip()
    expected_evidence = str(evidence_digest or "").strip()
    if not expected_posting or not expected_evidence:
        raise base.LeverPhaseBReviewedMaterialsError(
            "MATERIAL_BUNDLE_STALE posting and evidence digests are required"
        )

    matched_materials = []
    for material_type in base.MATERIAL_TYPES:
        material = base._latest_material(db, application.id, material_type)
        if material is None:
            raise base.LeverPhaseBReviewedMaterialsError(
                "MATERIAL_BUNDLE_STALE latest material bundle is incomplete"
            )
        if material.id != expected_ids[material_type]:
            raise base.LeverPhaseBReviewedMaterialsError(
                f"MATERIAL_BUNDLE_STALE {material_type} material changed after review"
            )
        if material.version != expected_versions[material_type]:
            raise base.LeverPhaseBReviewedMaterialsError(
                f"MATERIAL_BUNDLE_STALE {material_type} version changed after review"
            )
        preparation = base._preparation_snapshot(material)
        if str(preparation.get("posting_sha256") or "") != expected_posting:
            raise base.LeverPhaseBReviewedMaterialsError(
                f"MATERIAL_BUNDLE_STALE {material_type} posting context changed after review"
            )
        if str(preparation.get("evidence_digest") or "") != expected_evidence:
            raise base.LeverPhaseBReviewedMaterialsError(
                f"MATERIAL_BUNDLE_STALE {material_type} evidence changed after review"
            )
        matched_materials.append(material)

    if approved and all(
        str((material.source_snapshot or {}).get("user_review", {}).get("status") or "")
        == "approved"
        for material in matched_materials
    ):
        raise base.LeverPhaseBReviewedMaterialsError(
            "MATERIAL_BUNDLE_ALREADY_APPROVED exact displayed bundle was already approved"
        )

    return v5.review_current_lever_materials(
        db,
        user,
        application_id=application_id,
        approved=approved,
        notes=notes,
    )


__all__ = [
    "QUARANTINE_BLOCKER",
    "prepare_current_lever_operator_materials",
    "review_current_lever_operator_materials",
    "show_current_lever_operator_materials",
]
