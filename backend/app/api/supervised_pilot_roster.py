from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.schemas.lever_phase_b_current_intake import (
    CurrentLeverPhaseBImportIn,
    CurrentLeverPhaseBImportOut,
    CurrentLeverPhaseBMaterialReviewIn,
    CurrentLeverRuntimeArmIn,
)
from app.schemas.supervised_pilot_dossier import SupervisedPilotDossierOut
from app.schemas.supervised_pilot_roster import (
    LeverPhaseBLaunchOut,
    LeverPhaseBMaterialReviewIn,
    LeverPhaseBMaterialReviewOut,
    LeverPhaseBMaterializeOut,
    LeverPhaseBPrepareMaterialsOut,
    SupervisedPilotCandidateImportIn,
    SupervisedPilotCandidateImportOut,
    SupervisedPilotRosterOut,
)
from app.services.greenhouse_pilot_ingestion import (
    GreenhousePilotIngestionError,
    read_greenhouse_pilot_readiness,
)
from app.services.lever_phase_b_current_intake import (
    CurrentLeverPhaseBIntakeError,
    import_current_lever_phase_b_candidate,
)
from app.services.lever_phase_b_current_materials import LeverPhaseBReviewedMaterialsError
from app.services.lever_phase_b_current_operator import (
    prepare_current_lever_operator_materials,
    review_current_lever_operator_materials,
    show_current_lever_operator_materials,
)
from app.services.lever_phase_b_current_roster import (
    list_current_lever_phase_b_candidates,
)
from app.services.lever_phase_b_launch import LeverPhaseBLaunchError
from app.services.lever_phase_b_preparation import (
    enrich_lever_phase_b_preparation_status,
)
from app.services.lever_phase_b_reviewed_materials import (
    LeverPhaseBReviewedMaterialsError as RetainedLeverPhaseBReviewedMaterialsError,
    prepare_retained_lever_materials,
    review_retained_lever_materials,
)
from app.services.lever_phase_b_runtime import (
    build_runtime_lever_phase_b_launch_status,
    materialize_runtime_lever_phase_b_candidate,
)
from app.services.lever_pilot_control_request import (
    LeverPilotControlError,
    request_runtime_arm,
    request_runtime_disarm,
    runtime_control_status,
)
from app.services.lever_pilot_ledger_boundary import (
    LeverPilotIngestionError,
    read_lever_pilot_readiness,
)
from app.services.supervised_pilot_dossier import (
    SupervisedPilotDossierError,
    build_supervised_pilot_dossier,
)
from app.services.supervised_pilot_intake import (
    SupervisedPilotIntakeError,
    import_supervised_pilot_candidate,
)
from app.services.supervised_pilot_roster import build_supervised_pilot_roster


router = APIRouter(prefix="/supervised-pilot", tags=["supervised-pilot"])


def _greenhouse_readiness_or_none():
    try:
        return read_greenhouse_pilot_readiness()
    except GreenhousePilotIngestionError:
        return None


def _lever_readiness_or_none():
    try:
        return read_lever_pilot_readiness()
    except LeverPilotIngestionError:
        return None


def _readiness_by_platform():
    return {
        "greenhouse": _greenhouse_readiness_or_none(),
        "lever": _lever_readiness_or_none(),
    }


def _owned_application_records(
    db: Session,
    application_id: int,
    user_id: int,
) -> tuple[Application, Job]:
    application = (
        db.query(Application)
        .filter(
            Application.id == application_id,
            Application.user_id == user_id,
        )
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if not job:
        raise HTTPException(status_code=409, detail="Application job is missing")
    return application, job


@router.post(
    "/candidates",
    response_model=SupervisedPilotCandidateImportOut,
)
def import_supervised_pilot_application_candidate(
    data: SupervisedPilotCandidateImportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = import_supervised_pilot_candidate(
            db,
            current_user,
            employer=data.employer,
            role=data.role,
            application_url=data.application_url,
            location=data.location,
            notes=data.notes,
            source_reference=data.source_reference,
        )
    except SupervisedPilotIntakeError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    return result


@router.post(
    "/lever-candidates",
    response_model=CurrentLeverPhaseBImportOut,
    status_code=201,
)
async def import_current_lever_phase_b_application_candidate(
    data: CurrentLeverPhaseBImportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = await import_current_lever_phase_b_candidate(
            db,
            current_user,
            employer=data.employer,
            role=data.role,
            application_url=data.application_url,
            location=data.location,
            notes=data.notes,
            source_reference=data.source_reference,
        )
    except CurrentLeverPhaseBIntakeError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    return result


@router.get("/current-lever")
def current_lever_phase_b_roster(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read the owner-selected current Lever workspace without ranking or mutation."""

    result = list_current_lever_phase_b_candidates(db, current_user)
    db.rollback()
    return result


@router.get("/current-lever/runtime-control")
def current_lever_runtime_control_status(
    current_user: User = Depends(get_current_user),
):
    """Read native controller + process-bound lease truth without mutation."""

    return runtime_control_status(current_user)


@router.post(
    "/current-lever/{application_id}/runtime-control/arm",
    status_code=202,
)
def request_current_lever_runtime_arm(
    application_id: int,
    data: CurrentLeverRuntimeArmIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = request_runtime_arm(
            db,
            current_user,
            application_id=application_id,
            acknowledgment=data.acknowledgment,
        )
    except LeverPilotControlError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # The request file is the only mutation. Release the application row lock without
    # changing database state or creating a submission approval/attempt.
    db.rollback()
    return result


@router.post(
    "/current-lever/runtime-control/disarm",
    status_code=202,
)
def request_current_lever_runtime_disarm(
    current_user: User = Depends(get_current_user),
):
    try:
        return request_runtime_disarm(current_user)
    except LeverPilotControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/current-lever/{application_id}/materials")
def current_lever_phase_b_materials(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = show_current_lever_operator_materials(
            db,
            current_user,
            application_id=application_id,
        )
    except LeverPhaseBReviewedMaterialsError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.rollback()
    return result


@router.post("/current-lever/{application_id}/prepare-materials")
def prepare_current_lever_phase_b_materials(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = prepare_current_lever_operator_materials(
            db,
            current_user,
            application_id=application_id,
        )
    except LeverPhaseBReviewedMaterialsError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result


@router.post("/current-lever/{application_id}/review-materials")
def review_current_lever_phase_b_materials(
    application_id: int,
    data: CurrentLeverPhaseBMaterialReviewIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.approved:
        expected = f"APPROVE LEVER MATERIALS {application_id}"
        if str(data.acknowledgment or "").strip() != expected:
            raise HTTPException(
                status_code=409,
                detail="MATERIAL_APPROVAL_BLOCKED exact application-bound acknowledgment required",
            )

    try:
        result = review_current_lever_operator_materials(
            db,
            current_user,
            application_id=application_id,
            approved=data.approved,
            notes=data.notes,
            material_ids=data.material_ids,
            material_versions=data.material_versions,
            posting_sha256=data.posting_sha256,
            evidence_digest=data.evidence_digest,
        )
    except LeverPhaseBReviewedMaterialsError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result


@router.get(
    "/lever-launch",
    response_model=LeverPhaseBLaunchOut,
)
def lever_phase_b_launch(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        retained = build_runtime_lever_phase_b_launch_status(db, current_user)
        return enrich_lever_phase_b_preparation_status(
            db,
            current_user,
            retained,
        )
    except LeverPhaseBLaunchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/lever-launch/{review_id}/materialize",
    response_model=LeverPhaseBMaterializeOut,
)
def materialize_lever_phase_b_launch_candidate(
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = materialize_runtime_lever_phase_b_candidate(
            db,
            current_user,
            review_id=review_id,
        )
    except LeverPhaseBLaunchError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result


@router.post(
    "/lever-launch/{review_id}/prepare-materials",
    response_model=LeverPhaseBPrepareMaterialsOut,
)
def prepare_lever_phase_b_launch_materials(
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = prepare_retained_lever_materials(
            db,
            current_user,
            review_id=review_id,
        )
    except (LeverPhaseBLaunchError, RetainedLeverPhaseBReviewedMaterialsError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result


@router.post(
    "/lever-launch/{review_id}/review-materials",
    response_model=LeverPhaseBMaterialReviewOut,
)
def review_lever_phase_b_launch_materials(
    review_id: str,
    data: LeverPhaseBMaterialReviewIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = review_retained_lever_materials(
            db,
            current_user,
            review_id=review_id,
            approved=data.approved,
            notes=data.notes,
        )
    except (LeverPhaseBLaunchError, RetainedLeverPhaseBReviewedMaterialsError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    return result


@router.get("/roster", response_model=SupervisedPilotRosterOut)
def supervised_pilot_roster(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_supervised_pilot_roster(
        db,
        current_user,
        readiness=_greenhouse_readiness_or_none(),
    )


@router.get(
    "/applications/{application_id}/dossier",
    response_model=SupervisedPilotDossierOut,
)
def supervised_pilot_application_dossier(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application, job = _owned_application_records(
        db,
        application_id,
        current_user.id,
    )
    try:
        return build_supervised_pilot_dossier(
            db,
            application,
            current_user,
            job,
            readiness=_readiness_by_platform(),
        )
    except SupervisedPilotDossierError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
