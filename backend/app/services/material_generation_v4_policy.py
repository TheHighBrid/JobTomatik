from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.material import ApplicationMaterial
from app.models.user import User
from app.services import material_generation_v4 as v4


FILTERED_ROLE_WARNING = (
    "No source-backed current role or years-of-experience statement was available"
)


def _has_target_aligned_employment_claim(material: ApplicationMaterial) -> bool:
    return any(
        claim.get("category") in {"employment", "job_alignment", "career_summary"}
        and bool(claim.get("evidence_unit_ids"))
        for claim in (material.claims or [])
    )


def _normalize_intentional_filter_warnings(material: ApplicationMaterial) -> None:
    warnings = list(material.warnings or [])
    if FILTERED_ROLE_WARNING in warnings and _has_target_aligned_employment_claim(material):
        warnings = [warning for warning in warnings if warning != FILTERED_ROLE_WARNING]

    material.warnings = sorted(set(warnings))
    material.status = "verified" if not material.warnings else "needs_review"


def generate_application_material(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    material_type: str = "cover_letter",
    rebuild_evidence: bool = True,
) -> ApplicationMaterial:
    material = v4.generate_application_material(
        db,
        application,
        user,
        job,
        material_type=material_type,
        rebuild_evidence=rebuild_evidence,
    )
    _normalize_intentional_filter_warnings(material)
    db.flush()
    return material
