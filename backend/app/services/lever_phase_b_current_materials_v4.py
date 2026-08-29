"""Current Lever Phase B preparation using the target-aligned v4 material generator.

Only material preparation differs from the v3 service. Review, show, runtime, approval,
and submission boundaries remain owned by the existing current Lever service.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.application import ApplicationEvent
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.user import User
from app.services import lever_phase_b_current_materials as base
from app.services.application_state import normalize_state
from app.services.evidence_ledger import eligible_evidence_query, rebuild_user_evidence
from app.services.material_generation_v4 import generate_application_material


show_current_lever_materials = base.show_current_lever_materials
review_current_lever_materials = base.review_current_lever_materials
_fetch_current_hosted_posting = base._fetch_current_hosted_posting


def prepare_current_lever_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
) -> Dict[str, Any]:
    """Generate v4 target-aligned materials and open the existing explicit review task."""

    resume_path = base._required_resume_path(user)
    candidate, application, job = base._current_candidate_records(
        db, user, application_id, lock=True
    )
    posting_snapshot, posting_sha256 = base._posting_snapshot(
        candidate,
        _fetch_current_hosted_posting(candidate),
    )

    refreshed_at = base._utcnow()
    job.raw_data = {
        **(job.raw_data or {}),
        "lever_official_posting": posting_snapshot,
        "lever_official_posting_sha256": posting_sha256,
        "lever_official_posting_refreshed_at": refreshed_at,
        "material_preparation_source": base.REVIEW_STAGE,
    }
    job.description = posting_snapshot["description_plain"]
    job.requirements = posting_snapshot.get("requirements_plain")
    application.application_target_metadata = {
        **(application.application_target_metadata or {}),
        "lever_official_posting_sha256": posting_sha256,
        "lever_official_posting_refreshed_at": refreshed_at,
        "requires_fresh_runtime_preflight": True,
    }
    application.resume_path = str(resume_path)

    evidence_result = rebuild_user_evidence(db, user)
    eligible = eligible_evidence_query(db, user.id).order_by(EvidenceUnit.id).all()
    resume_units = [unit for unit in eligible if unit.source_type == "resume_pdf"]
    if not resume_units:
        raise base.LeverPhaseBReviewedMaterialsError(
            "The résumé was readable as a file but produced no source-backed text evidence"
        )
    evidence_digest = base._evidence_digest(eligible)

    materials: list[ApplicationMaterial] = []
    all_critical_errors: list[str] = []
    for material_type in base.MATERIAL_TYPES:
        material = generate_application_material(
            db,
            application,
            user,
            job,
            material_type=material_type,
            rebuild_evidence=False,
        )
        critical_errors = base._critical_material_errors(material, eligible)
        base._set_material_preparation_snapshot(
            material,
            candidate=candidate,
            posting_sha256=posting_sha256,
            evidence_digest=evidence_digest,
            critical_errors=critical_errors,
        )
        materials.append(material)
        all_critical_errors.extend(critical_errors)
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="lever_phase_b_verified_material_generated",
                from_state=normalize_state(application.automation_state),
                to_state=normalize_state(application.automation_state),
                payload={
                    "review_id": candidate["review_id"],
                    "material_id": material.id,
                    "material_type": material.material_type,
                    "material_version": material.version,
                    "material_status": material.status,
                    "material_generator_version": material.generator_version,
                    "posting_sha256": posting_sha256,
                    "evidence_digest": evidence_digest,
                    "critical_error_count": len(critical_errors),
                    "current_lever_application_id": application.id,
                    "submission_queued": False,
                    "approval_issued": False,
                },
            )
        )

    unique_critical = sorted(set(all_critical_errors))
    base._upsert_material_review_task(
        db,
        application,
        summary=(
            "Generated current Lever materials have source-validation blockers."
            if unique_critical
            else "Review both latest source-backed current Lever materials before preflight."
        ),
        details={
            "stage": base.REVIEW_STAGE,
            "review_id": candidate["review_id"],
            "material_ids": [material.id for material in materials],
            "material_versions": {
                material.material_type: material.version for material in materials
            },
            "material_generator_versions": {
                material.material_type: material.generator_version for material in materials
            },
            "posting_sha256": posting_sha256,
            "evidence_digest": evidence_digest,
            "review_eligible": not unique_critical,
            "critical_errors": unique_critical,
            "current_lever_application_id": application.id,
        },
        blocking_url=candidate["application_url"],
    )

    return {
        "review_id": candidate["review_id"],
        "application_id": application.id,
        "job_id": job.id,
        "posting_sha256": posting_sha256,
        "posting_source": posting_snapshot["source"],
        "resume_filename": user.resume_filename or resume_path.name,
        "resume_evidence_count": len(resume_units),
        "evidence_unit_count": len(eligible),
        "evidence_digest": evidence_digest,
        "evidence_rebuild": evidence_result,
        "review_eligible": not unique_critical,
        "critical_errors": unique_critical,
        "materials": [
            {
                "id": material.id,
                "material_type": material.material_type,
                "version": material.version,
                "generator_version": material.generator_version,
                "status": material.status,
                "warning_count": len(material.warnings or []),
                "review_status": "pending",
            }
            for material in materials
        ],
        "automation_state": normalize_state(application.automation_state),
        "requires_explicit_material_review": True,
        "requires_fresh_runtime_preflight": True,
        "approval_issued": False,
        "submission_queued": False,
        "runtime_flags_changed": False,
    }
