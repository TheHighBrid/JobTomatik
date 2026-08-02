from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.user import User
from app.schemas.material import (
    ApplicationMaterialOut,
    EvidenceRebuildOut,
    EvidenceUnitCreate,
    EvidenceUnitOut,
    EvidenceUnitUpdate,
    MaterialGenerationOut,
)
from app.services.evidence_ledger import (
    create_manual_evidence,
    evidence_hash,
    rebuild_user_evidence,
)
from app.services.material_generation import (
    SUPPORTED_MATERIAL_TYPES,
    generate_application_material,
)

router = APIRouter(prefix="/materials", tags=["materials"])


def _application_for_user(db: Session, application_id: int, user_id: int) -> Application:
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user_id)
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _load_material(db: Session, material_id: int, user_id: int) -> ApplicationMaterial:
    material = (
        db.query(ApplicationMaterial)
        .options(
            joinedload(ApplicationMaterial.evidence_links).joinedload(
                "evidence_unit"
            )
        )
        .filter(
            ApplicationMaterial.id == material_id,
            ApplicationMaterial.user_id == user_id,
        )
        .first()
    )
    if not material:
        raise HTTPException(status_code=404, detail="Application material not found")
    return material


@router.get("/evidence", response_model=List[EvidenceUnitOut])
def list_evidence(
    kind: Optional[str] = None,
    source_type: Optional[str] = None,
    verification_status: Optional[str] = None,
    active_only: bool = True,
    limit: int = Query(250, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(EvidenceUnit).filter(EvidenceUnit.user_id == current_user.id)
    if active_only:
        query = query.filter(EvidenceUnit.is_active.is_(True))
    if kind:
        query = query.filter(EvidenceUnit.kind == kind.strip().lower())
    if source_type:
        query = query.filter(EvidenceUnit.source_type == source_type.strip().lower())
    if verification_status:
        query = query.filter(
            EvidenceUnit.verification_status == verification_status.strip().lower()
        )
    return query.order_by(EvidenceUnit.kind, EvidenceUnit.created_at.desc()).limit(limit).all()


@router.post("/evidence/rebuild", response_model=EvidenceRebuildOut)
def rebuild_evidence(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = rebuild_user_evidence(db, current_user)
    db.commit()
    return result


@router.post("/evidence", response_model=EvidenceUnitOut, status_code=201)
def add_evidence(
    data: EvidenceUnitCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unit = create_manual_evidence(
        db,
        current_user,
        kind=data.kind.strip().lower(),
        label=data.label,
        statement=data.statement,
        organization=data.organization,
        role=data.role,
        source_ref=data.source_ref,
        confidence=data.confidence,
        provenance=data.provenance,
    )
    db.commit()
    db.refresh(unit)
    return unit


@router.patch("/evidence/{evidence_id}", response_model=EvidenceUnitOut)
def update_evidence(
    evidence_id: int,
    data: EvidenceUnitUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unit = (
        db.query(EvidenceUnit)
        .filter(EvidenceUnit.id == evidence_id, EvidenceUnit.user_id == current_user.id)
        .first()
    )
    if not unit:
        raise HTTPException(status_code=404, detail="Evidence unit not found")

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field in {"label", "statement", "organization", "role"} and value is not None:
            value = value.strip()
        if field == "verification_status" and value is not None:
            value = value.strip().lower()
        setattr(unit, field, value)

    if any(field in updates for field in {"statement", "organization", "role"}):
        unit.source_hash = evidence_hash(
            unit.statement,
            kind=unit.kind,
            organization=unit.organization or "",
            role=unit.role or "",
        )
        unit.provenance = {
            **(unit.provenance or {}),
            "edited_by_user": True,
        }
        unit.verification_status = "user_confirmed"

    db.commit()
    db.refresh(unit)
    return unit


@router.delete("/evidence/{evidence_id}", status_code=204)
def deactivate_evidence(
    evidence_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unit = (
        db.query(EvidenceUnit)
        .filter(EvidenceUnit.id == evidence_id, EvidenceUnit.user_id == current_user.id)
        .first()
    )
    if not unit:
        raise HTTPException(status_code=404, detail="Evidence unit not found")
    unit.is_active = False
    db.commit()


@router.get(
    "/applications/{application_id}",
    response_model=List[ApplicationMaterialOut],
)
def list_application_materials(
    application_id: int,
    material_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _application_for_user(db, application_id, current_user.id)
    query = (
        db.query(ApplicationMaterial)
        .options(
            joinedload(ApplicationMaterial.evidence_links).joinedload(
                "evidence_unit"
            )
        )
        .filter(
            ApplicationMaterial.application_id == application_id,
            ApplicationMaterial.user_id == current_user.id,
        )
    )
    if material_type:
        if material_type not in SUPPORTED_MATERIAL_TYPES:
            raise HTTPException(status_code=422, detail="Unsupported material type")
        query = query.filter(ApplicationMaterial.material_type == material_type)
    return query.order_by(
        ApplicationMaterial.material_type,
        ApplicationMaterial.version.desc(),
    ).all()


@router.post(
    "/applications/{application_id}/generate",
    response_model=MaterialGenerationOut,
)
def generate_material(
    application_id: int,
    material_type: str = Query("cover_letter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if material_type not in SUPPORTED_MATERIAL_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"material_type must be one of {sorted(SUPPORTED_MATERIAL_TYPES)}",
        )
    application = _application_for_user(db, application_id, current_user.id)
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    material = generate_application_material(
        db,
        application,
        current_user,
        job,
        material_type=material_type,
    )
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="verified_material_generated",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "material_id": material.id,
                "material_type": material.material_type,
                "version": material.version,
                "status": material.status,
                "claim_count": len(material.claims or []),
                "warning_count": len(material.warnings or []),
            },
        )
    )
    db.commit()
    material = _load_material(db, material.id, current_user.id)
    verified_claims = sum(
        1
        for claim in material.claims or []
        if not claim.get("applicant_fact", True)
        or bool(claim.get("evidence_unit_ids"))
    )
    return {
        "material": material,
        "evidence_unit_count": len(material.evidence_links or []),
        "verified_claim_count": verified_claims,
        "warning_count": len(material.warnings or []),
    }


@router.post("/applications/{application_id}/generate-bundle")
def generate_material_bundle(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _application_for_user(db, application_id, current_user.id)
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    materials = [
        generate_application_material(
            db,
            application,
            current_user,
            job,
            material_type=material_type,
            rebuild_evidence=index == 0,
        )
        for index, material_type in enumerate(("cover_letter", "resume_summary"))
    ]
    for material in materials:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="verified_material_generated",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "material_id": material.id,
                    "material_type": material.material_type,
                    "version": material.version,
                    "status": material.status,
                },
            )
        )
    db.commit()
    return {
        "application_id": application.id,
        "materials": [
            {
                "id": material.id,
                "material_type": material.material_type,
                "version": material.version,
                "status": material.status,
                "warning_count": len(material.warnings or []),
            }
            for material in materials
        ],
    }


@router.get("/{material_id}", response_model=ApplicationMaterialOut)
def get_material(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _load_material(db, material_id, current_user.id)
