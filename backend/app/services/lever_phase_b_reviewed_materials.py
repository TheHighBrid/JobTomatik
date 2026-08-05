"""Prepare and explicitly review real materials for retained Lever candidates.

The preparation path may read the exact public Lever posting metadata endpoint. It
never opens an application form, inspects DOM controls, issues or consumes an
approval, queues a worker, creates a submission attempt, or clicks final submit.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import httpx
from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.user import User
from app.services.application_state import (
    normalize_state,
    transition_application_state,
)
from app.services.ats_lever import (
    LEVER_EU_API_HOST,
    LEVER_GLOBAL_API_HOST,
    inspect_lever_posting,
)
from app.services.evidence_ledger import (
    eligible_evidence_query,
    rebuild_user_evidence,
)
from app.services.lever_phase_b_runtime import (
    build_runtime_lever_phase_b_launch_status,
    canonical_lever_application_url,
    materialize_runtime_lever_phase_b_candidate,
    read_runtime_lever_phase_b_launch,
)
from app.services.material_generation import (
    generate_application_material,
    validate_claims,
)


REVIEW_STAGE = "lever_phase_b_material_review"
REVIEW_REASON = "lever_phase_b_material_review_required"
SUPPORTED_LOCAL_STATES = {
    ApplicationAutomationState.preparing.value,
    ApplicationAutomationState.ready_to_apply.value,
    ApplicationAutomationState.needs_review.value,
}
MATERIAL_TYPES = ("cover_letter", "resume_summary")


class LeverPhaseBReviewedMaterialsError(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_resume_path(user: User) -> Path:
    raw = str(user.resume_path or "").strip()
    if not raw:
        raise LeverPhaseBReviewedMaterialsError(
            "Upload the owner résumé before preparing retained Lever materials"
        )
    path = Path(raw)
    if not path.is_file():
        raise LeverPhaseBReviewedMaterialsError(
            "The owner résumé file is missing or unreadable"
        )
    return path


def _retained_candidate(review_id: str) -> Dict[str, Any]:
    requested = str(review_id or "").strip()
    launch = read_runtime_lever_phase_b_launch()
    matches = [
        candidate
        for candidate in launch["candidates"]
        if candidate["review_id"] == requested
    ]
    if len(matches) != 1:
        raise LeverPhaseBReviewedMaterialsError(
            "Retained Lever launch candidate was not found"
        )
    return dict(matches[0])


def _fetch_official_posting(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    host = (
        LEVER_EU_API_HOST
        if str(candidate.get("region") or "").lower() == "eu"
        else LEVER_GLOBAL_API_HOST
    )
    url = (
        f"https://{host}/v0/postings/{candidate['site']}/"
        f"{candidate['posting_id']}"
    )
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(url, params={"mode": "json"})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise LeverPhaseBReviewedMaterialsError(
            "The exact official Lever posting metadata could not be refreshed"
        ) from exc
    if not isinstance(payload, dict):
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever posting metadata was not an object"
        )
    return payload


def _plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _requirements_text(payload: Mapping[str, Any]) -> Optional[str]:
    matched = []
    for item in payload.get("lists") or []:
        if not isinstance(item, Mapping):
            continue
        heading = _plain_text(item.get("text")).casefold()
        if any(
            term in heading
            for term in (
                "requirement",
                "qualification",
                "what you bring",
                "what we're looking for",
                "what we are looking for",
                "about you",
            )
        ):
            content = _plain_text(item.get("content"))
            if content:
                matched.append(content)
    return "\n".join(matched) or None


def _posting_snapshot(
    candidate: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[Dict[str, Any], str]:
    inspected = inspect_lever_posting(dict(payload))
    if not inspected.get("posting_metadata_certified"):
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever posting metadata failed certification"
        )
    if str(inspected.get("posting_id") or "") != str(candidate["posting_id"]):
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever posting ID drifted from the retained target"
        )
    if str(inspected.get("site") or "").casefold() != str(
        candidate["site"]
    ).casefold():
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever site drifted from the retained target"
        )
    if str(inspected.get("region") or "").casefold() != str(
        candidate["region"]
    ).casefold():
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever region drifted from the retained target"
        )
    official_apply = canonical_lever_application_url(
        str(inspected.get("apply_url") or "")
    )
    if official_apply != candidate["application_url"]:
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever apply URL drifted from the retained target"
        )
    if str(inspected.get("title") or "").strip().casefold() != str(
        candidate["role"]
    ).strip().casefold():
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever role drifted from the retained target"
        )

    description = _plain_text(payload.get("descriptionPlain"))
    if not description:
        raise LeverPhaseBReviewedMaterialsError(
            "The official Lever posting has no usable plain-text description"
        )
    snapshot = {
        "posting_id": str(payload.get("id") or ""),
        "title": str(payload.get("text") or "").strip(),
        "categories": payload.get("categories") or {},
        "description_plain": description,
        "requirements_plain": _requirements_text(payload),
        "hosted_url": str(payload.get("hostedUrl") or "").strip(),
        "apply_url": official_apply,
        "site": str(candidate["site"]),
        "region": str(candidate["region"]),
        "source": "lever_official_postings_api",
    }
    digest = hashlib.sha256(
        json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return snapshot, digest


def _application_records(
    db: Session,
    user: User,
    application_id: int,
    job_id: int,
) -> tuple[Application, Job]:
    application = (
        db.query(Application)
        .filter(
            Application.id == application_id,
            Application.user_id == user.id,
        )
        .with_for_update()
        .first()
    )
    job = db.query(Job).filter(Job.id == job_id).first()
    if not application or not job or application.job_id != job.id:
        raise LeverPhaseBReviewedMaterialsError(
            "The materialized Lever application record is incomplete"
        )
    state = normalize_state(application.automation_state)
    if state not in SUPPORTED_LOCAL_STATES:
        raise LeverPhaseBReviewedMaterialsError(
            "The application already entered an execution or terminal state"
        )
    return application, job


def _latest_material(
    db: Session,
    application_id: int,
    material_type: str,
) -> Optional[ApplicationMaterial]:
    return (
        db.query(ApplicationMaterial)
        .filter(
            ApplicationMaterial.application_id == application_id,
            ApplicationMaterial.material_type == material_type,
        )
        .order_by(
            ApplicationMaterial.version.desc(),
            ApplicationMaterial.id.desc(),
        )
        .first()
    )


def _substantive_claims(material: ApplicationMaterial) -> list[Dict[str, Any]]:
    return [
        claim
        for claim in material.claims or []
        if claim.get("applicant_fact", True)
        and claim.get("category") not in {"identity"}
        and claim.get("evidence_unit_ids")
    ]


def _critical_material_errors(
    material: ApplicationMaterial,
    eligible_units: Iterable[EvidenceUnit],
) -> list[str]:
    errors = list(validate_claims(list(material.claims or []), eligible_units))
    if not _substantive_claims(material):
        errors.append(
            "No substantive applicant claim could be supported by active evidence"
        )
    return sorted(set(errors))


def _set_material_preparation_snapshot(
    material: ApplicationMaterial,
    *,
    candidate: Mapping[str, Any],
    posting_sha256: str,
    evidence_digest: str,
    critical_errors: list[str],
) -> None:
    snapshot = dict(material.source_snapshot or {})
    snapshot["lever_phase_b_preparation"] = {
        "review_id": candidate["review_id"],
        "launch_application_id": candidate["application_id"],
        "posting_sha256": posting_sha256,
        "evidence_digest": evidence_digest,
        "prepared_at": _utcnow(),
        "review_eligible": not critical_errors,
        "critical_errors": critical_errors,
    }
    snapshot["user_review"] = {
        "status": "pending",
        "reviewed_at": None,
        "reviewed_by_user_id": None,
        "notes": None,
    }
    material.source_snapshot = snapshot


def _evidence_digest(units: Iterable[EvidenceUnit]) -> str:
    payload = [
        {
            "id": unit.id,
            "source_hash": unit.source_hash,
            "source_type": unit.source_type,
            "source_ref": unit.source_ref,
        }
        for unit in sorted(units, key=lambda item: item.id)
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _upsert_material_review_task(
    db: Session,
    application: Application,
    *,
    summary: str,
    details: Mapping[str, Any],
    blocking_url: str,
) -> ManualReviewTask:
    tasks = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.reason_code == REVIEW_REASON,
            ManualReviewTask.status.in_(
                [
                    ManualReviewStatus.open.value,
                    ManualReviewStatus.in_progress.value,
                ]
            ),
        )
        .order_by(ManualReviewTask.id.asc())
        .all()
    )
    task = next(
        (
            item
            for item in tasks
            if (item.details or {}).get("stage") == REVIEW_STAGE
        ),
        None,
    )
    if task is None:
        task = ManualReviewTask(
            application_id=application.id,
            reason_code=REVIEW_REASON,
            status=ManualReviewStatus.open.value,
            summary=summary,
            details=dict(details),
            blocking_url=blocking_url,
        )
        db.add(task)
    else:
        task.status = ManualReviewStatus.open.value
        task.summary = summary
        task.details = dict(details)
        task.blocking_url = blocking_url
        task.resolved_at = None
        task.resolution_notes = None

    current_state = normalize_state(application.automation_state)
    if current_state != ApplicationAutomationState.needs_review.value:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.needs_review,
            "lever_phase_b_material_review_required",
            {
                "stage": REVIEW_STAGE,
                "review_id": details.get("review_id"),
                "review_eligible": bool(details.get("review_eligible")),
                "critical_error_count": len(details.get("critical_errors") or []),
                "approval_issued": False,
                "submission_queued": False,
            },
        )
    db.flush()
    return task


def _resolve_material_review_tasks(
    db: Session,
    application_id: int,
    *,
    notes: Optional[str],
) -> None:
    tasks = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application_id,
            ManualReviewTask.reason_code == REVIEW_REASON,
            ManualReviewTask.status.in_(
                [
                    ManualReviewStatus.open.value,
                    ManualReviewStatus.in_progress.value,
                ]
            ),
        )
        .all()
    )
    for task in tasks:
        if (task.details or {}).get("stage") != REVIEW_STAGE:
            continue
        task.status = ManualReviewStatus.resolved.value
        task.resolved_at = datetime.utcnow()
        task.resolution_notes = notes or "Latest materials explicitly reviewed."
    db.flush()


def _open_review_count(db: Session, application_id: int) -> int:
    return (
        db.query(ManualReviewTask.id)
        .filter(
            ManualReviewTask.application_id == application_id,
            ManualReviewTask.status.in_(
                [
                    ManualReviewStatus.open.value,
                    ManualReviewStatus.in_progress.value,
                ]
            ),
        )
        .count()
    )


def prepare_retained_lever_materials(
    db: Session,
    user: User,
    *,
    review_id: str,
) -> Dict[str, Any]:
    resume_path = _required_resume_path(user)
    candidate = _retained_candidate(review_id)
    posting_snapshot, posting_sha256 = _posting_snapshot(
        candidate,
        _fetch_official_posting(candidate),
    )

    materialized = materialize_runtime_lever_phase_b_candidate(
        db,
        user,
        review_id=candidate["review_id"],
    )
    application, job = _application_records(
        db,
        user,
        int(materialized["application_id"]),
        int(materialized["job_id"]),
    )

    refreshed_at = _utcnow()
    job.raw_data = {
        **(job.raw_data or {}),
        "lever_official_posting": posting_snapshot,
        "lever_official_posting_sha256": posting_sha256,
        "lever_official_posting_refreshed_at": refreshed_at,
        "material_preparation_source": REVIEW_STAGE,
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
        raise LeverPhaseBReviewedMaterialsError(
            "The résumé was readable as a file but produced no source-backed text evidence"
        )
    evidence_sha256 = _evidence_digest(eligible)

    materials = []
    all_critical_errors: list[str] = []
    for material_type in MATERIAL_TYPES:
        material = generate_application_material(
            db,
            application,
            user,
            job,
            material_type=material_type,
            rebuild_evidence=False,
        )
        critical_errors = _critical_material_errors(material, eligible)
        _set_material_preparation_snapshot(
            material,
            candidate=candidate,
            posting_sha256=posting_sha256,
            evidence_digest=evidence_sha256,
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
                    "posting_sha256": posting_sha256,
                    "evidence_digest": evidence_sha256,
                    "critical_error_count": len(critical_errors),
                    "submission_queued": False,
                    "approval_issued": False,
                },
            )
        )

    unique_critical = sorted(set(all_critical_errors))
    _upsert_material_review_task(
        db,
        application,
        summary=(
            "Generated Lever materials have source-validation blockers."
            if unique_critical
            else "Review both latest source-backed Lever materials before preflight."
        ),
        details={
            "stage": REVIEW_STAGE,
            "review_id": candidate["review_id"],
            "material_ids": [material.id for material in materials],
            "material_versions": {
                material.material_type: material.version for material in materials
            },
            "posting_sha256": posting_sha256,
            "evidence_digest": evidence_sha256,
            "review_eligible": not unique_critical,
            "critical_errors": unique_critical,
        },
        blocking_url=candidate["application_url"],
    )

    return {
        "review_id": candidate["review_id"],
        "launch_application_id": candidate["application_id"],
        "application_id": application.id,
        "job_id": job.id,
        "posting_sha256": posting_sha256,
        "posting_source": "lever_official_postings_api",
        "resume_filename": user.resume_filename or resume_path.name,
        "resume_evidence_count": len(resume_units),
        "evidence_unit_count": len(eligible),
        "evidence_digest": evidence_sha256,
        "evidence_rebuild": evidence_result,
        "review_eligible": not unique_critical,
        "critical_errors": unique_critical,
        "materials": [
            {
                "id": material.id,
                "material_type": material.material_type,
                "version": material.version,
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
    }


def _preparation_snapshot(material: ApplicationMaterial) -> Dict[str, Any]:
    snapshot = material.source_snapshot or {}
    preparation = snapshot.get("lever_phase_b_preparation")
    return dict(preparation) if isinstance(preparation, Mapping) else {}


def review_retained_lever_materials(
    db: Session,
    user: User,
    *,
    review_id: str,
    approved: bool,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    candidate = _retained_candidate(review_id)
    launch_status = build_runtime_lever_phase_b_launch_status(db, user)
    status_candidate = next(
        (
            item
            for item in launch_status["candidates"]
            if item["review_id"] == candidate["review_id"]
        ),
        None,
    )
    if not status_candidate or not status_candidate.get("materialized"):
        raise LeverPhaseBReviewedMaterialsError(
            "Prepare the retained candidate before reviewing materials"
        )
    application, job = _application_records(
        db,
        user,
        int(status_candidate["materialized_application_id"]),
        int(status_candidate["job_id"]),
    )
    posting_sha256 = str(
        (job.raw_data or {}).get("lever_official_posting_sha256") or ""
    )
    if not posting_sha256:
        raise LeverPhaseBReviewedMaterialsError(
            "The exact official Lever posting context is missing"
        )

    materials = {
        material_type: _latest_material(db, application.id, material_type)
        for material_type in MATERIAL_TYPES
    }
    if any(material is None for material in materials.values()):
        raise LeverPhaseBReviewedMaterialsError(
            "Both latest Lever material types must exist before review"
        )

    eligible = eligible_evidence_query(db, user.id).order_by(EvidenceUnit.id).all()
    current_evidence_digest = _evidence_digest(eligible)
    critical_errors: list[str] = []
    for material in materials.values():
        assert material is not None
        preparation = _preparation_snapshot(material)
        if preparation.get("posting_sha256") != posting_sha256:
            critical_errors.append(
                f"{material.material_type} was generated from stale posting context"
            )
        if preparation.get("evidence_digest") != current_evidence_digest:
            critical_errors.append(
                f"{material.material_type} was generated from stale evidence"
            )
        critical_errors.extend(_critical_material_errors(material, eligible))

    unique_critical = sorted(set(critical_errors))
    if approved and unique_critical:
        raise LeverPhaseBReviewedMaterialsError(
            "The latest materials cannot be approved because source validation failed: "
            + "; ".join(unique_critical[:5])
        )

    reviewed_at = _utcnow()
    for material in materials.values():
        assert material is not None
        material.source_snapshot = {
            **(material.source_snapshot or {}),
            "user_review": {
                "status": "approved" if approved else "rejected",
                "reviewed_at": reviewed_at,
                "reviewed_by_user_id": user.id,
                "notes": str(notes or "").strip() or None,
                "accepted_warning_count": (
                    len(material.warnings or []) if approved else 0
                ),
            },
        }
        material.status = "verified" if approved else "needs_review"

    if not approved:
        _upsert_material_review_task(
            db,
            application,
            summary="The owner rejected the latest retained Lever material bundle.",
            details={
                "stage": REVIEW_STAGE,
                "review_id": candidate["review_id"],
                "material_ids": [material.id for material in materials.values()],
                "review_eligible": not unique_critical,
                "critical_errors": unique_critical,
                "owner_rejected": True,
            },
            blocking_url=candidate["application_url"],
        )
        return {
            "review_id": candidate["review_id"],
            "application_id": application.id,
            "approved": False,
            "material_review_status": "rejected",
            "ready_for_fresh_preflight": False,
            "automation_state": normalize_state(application.automation_state),
            "open_review_count": _open_review_count(db, application.id),
            "approval_issued": False,
            "submission_queued": False,
        }

    _required_resume_path(user)
    cover_letter = materials["cover_letter"]
    assert cover_letter is not None
    application.cover_letter = cover_letter.content
    application.resume_path = user.resume_path
    _resolve_material_review_tasks(db, application.id, notes=notes)
    remaining_reviews = _open_review_count(db, application.id)
    ready = remaining_reviews == 0
    current_state = normalize_state(application.automation_state)
    if ready:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.ready_to_apply,
            "lever_phase_b_material_bundle_reviewed",
            {
                "review_id": candidate["review_id"],
                "material_ids": [material.id for material in materials.values()],
                "posting_sha256": posting_sha256,
                "evidence_digest": current_evidence_digest,
                "requires_fresh_runtime_preflight": True,
                "approval_issued": False,
                "submission_queued": False,
            },
        )
    else:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="lever_phase_b_material_bundle_reviewed_with_other_blockers",
                from_state=current_state,
                to_state=current_state,
                payload={
                    "review_id": candidate["review_id"],
                    "remaining_open_review_count": remaining_reviews,
                    "requires_fresh_runtime_preflight": True,
                },
            )
        )

    db.flush()
    return {
        "review_id": candidate["review_id"],
        "application_id": application.id,
        "approved": True,
        "material_review_status": "approved",
        "ready_for_fresh_preflight": ready,
        "automation_state": normalize_state(application.automation_state),
        "open_review_count": remaining_reviews,
        "posting_sha256": posting_sha256,
        "evidence_digest": current_evidence_digest,
        "requires_fresh_runtime_preflight": True,
        "approval_issued": False,
        "submission_queued": False,
    }


__all__ = [
    "LeverPhaseBReviewedMaterialsError",
    "prepare_retained_lever_materials",
    "review_retained_lever_materials",
]
