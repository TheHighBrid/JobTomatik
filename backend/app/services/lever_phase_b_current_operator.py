"""Fail-closed operator boundary for current owner-selected Lever Phase B work.

This module wraps the existing current-material services with protections that must
hold for every mutating operator surface:

1. an application with any durable uncertain live submission attempt is quarantined
   from further material mutation or retry preparation;
2. a material review decision is bound to the exact bundle the owner inspected;
3. an already-approved exact bundle cannot be approved twice.

The wrapper never issues submission approval, queues work, opens a browser, changes
runtime flags, or submits an application.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.models.user import User
from app.services import lever_phase_b_current_materials as base
from app.services import lever_phase_b_current_materials_v5 as v5


QUARANTINE_BLOCKER = "submission_attempt_uncertain_no_retry"


def _lock_and_assert_mutation_allowed(
    db: Session,
    user: User,
    application_id: int,
) -> Application:
    application = (
        db.query(Application)
        .filter(
            Application.id == int(application_id),
            Application.user_id == user.id,
        )
        .with_for_update()
        .first()
    )
    if application is None:
        raise base.LeverPhaseBReviewedMaterialsError(
            "Current Lever application was not found"
        )

    uncertain = (
        db.query(SubmissionAttempt.id)
        .filter(
            SubmissionAttempt.application_id == application.id,
            SubmissionAttempt.status == SubmissionAttemptStatus.uncertain.value,
        )
        .first()
    )
    if uncertain is not None:
        raise base.LeverPhaseBReviewedMaterialsError(
            "Current Lever application is quarantined because a prior live "
            "submission attempt is uncertain; material mutation and retry are blocked"
        )
    return application


def prepare_current_lever_operator_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
) -> Dict[str, Any]:
    """Prepare current v5 materials only when no uncertain attempt exists."""

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
    """Read materials even for quarantined applications; this never mutates state."""

    return v5.show_current_lever_materials(
        db,
        user,
        application_id=application_id,
    )


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

    The application row remains locked from the quarantine check through the final
    review call, so a concurrent prepare path cannot replace the bundle in between
    the identity comparison and the recorded decision.
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
