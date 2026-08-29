from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.material import ApplicationMaterial
from app.models.user import User
from app.services import material_generation_v5 as v5


V5_STRUCTURAL_HEADINGS = (
    "EMPLOYMENT HISTORY",
    "RELEVANT SUPPORT EXPERIENCE",
)


def _normalize_v5_structural_warnings(material: ApplicationMaterial) -> None:
    """Remove only v4 heading warnings for v5's explicit separated resume sections.

    V5 intentionally separates dated employer headers from support bullets whose source
    employment cannot be proven. The inherited v4 checker treats every unfamiliar
    all-caps resume heading as suspicious. These two exact headings are part of the v5
    renderer contract, so their exact warning strings are non-blocking. Every other
    warning remains fail-closed.
    """

    content = str(material.content or "")
    warnings = list(material.warnings or [])
    for heading in V5_STRUCTURAL_HEADINGS:
        warning = (
            "Generated material contains an unexpected résumé section heading: "
            + heading
        )
        if warning in warnings and f"\n{heading}\n" in f"\n{content}":
            warnings = [item for item in warnings if item != warning]

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
    material = v5.generate_application_material(
        db,
        application,
        user,
        job,
        material_type=material_type,
        rebuild_evidence=rebuild_evidence,
    )
    _normalize_v5_structural_warnings(material)
    db.flush()
    return material
