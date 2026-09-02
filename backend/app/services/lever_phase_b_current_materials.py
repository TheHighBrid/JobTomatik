"""Evidence-backed reviewed materials for current owner-selected Lever Phase B jobs.

This service operates only on applications created by the preparation-only current
Lever intake. It may read the exact public hosted Lever posting and user-owned
JobTomatik evidence. It never issues a submission approval, changes live runtime
flags, queues a submission task, opens a browser, or submits an application.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
)
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.user import User
from app.services.application_state import normalize_state, transition_application_state
from app.services.ats_lever import inspect_lever_posting
from app.services.evidence_ledger import eligible_evidence_query, rebuild_user_evidence
from app.services.lever_phase_b_current_intake import INTAKE_SOURCE
from app.services.lever_phase_b_reviewed_materials import (
    MATERIAL_TYPES,
    REVIEW_STAGE,
    SUPPORTED_LOCAL_STATES,
    LeverPhaseBReviewedMaterialsError,
    _critical_material_errors,
    _evidence_digest,
    _latest_material,
    _open_review_count,
    _preparation_snapshot,
    _required_resume_path,
    _resolve_material_review_tasks,
    _set_material_preparation_snapshot,
    _upsert_material_review_task,
    _utcnow,
)
from app.services.lever_phase_b_runtime import canonical_lever_application_url
from app.services.material_generation import generate_application_material
from app.services.supervised_target_identity import persisted_supervised_target_metadata


HOSTED_TIMEOUT_SECONDS = 15.0


def _clean_html_text(value: str) -> str:
    source = value or ""
    source = re.sub(
        r"<(script|style|noscript)\b[^>]*>.*?</\1>",
        " ",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source = re.sub(r"<br\s*/?>", "\n", source, flags=re.IGNORECASE)
    source = re.sub(r"</(?:p|li|div|section|h[1-6])\s*>", "\n", source, flags=re.IGNORECASE)
    source = re.sub(r"<[^>]+>", " ", source)
    lines = [" ".join(html.unescape(line).split()) for line in source.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _hosted_role(body: str) -> Optional[str]:
    patterns = (
        r'<div[^>]*class=["\'][^"\']*posting-headline[^"\']*["\'][^>]*>.*?<h2[^>]*>(.*?)</h2>',
        r'<h2[^>]*>(.*?)</h2>',
    )
    for pattern in patterns:
        match = re.search(pattern, body or "", flags=re.IGNORECASE | re.DOTALL)
        if match:
            role = _clean_html_text(match.group(1))
            if role:
                return role
    return None


def _current_candidate_records(
    db: Session,
    user: User,
    application_id: int,
    *,
    lock: bool,
) -> tuple[Dict[str, Any], Application, Job]:
    query = db.query(Application).filter(
        Application.id == int(application_id),
        Application.user_id == user.id,
    )
    if lock:
        query = query.with_for_update()
    application = query.first()
    if application is None:
        raise LeverPhaseBReviewedMaterialsError("Current Lever application was not found")

    job = db.query(Job).filter(Job.id == application.job_id).first()
    if job is None:
        raise LeverPhaseBReviewedMaterialsError("Current Lever application job is missing")
    if str((job.raw_data or {}).get("selection_source") or "") != INTAKE_SOURCE:
        raise LeverPhaseBReviewedMaterialsError(
            "Application is not a current owner-selected Lever Phase B target"
        )

    state = normalize_state(application.automation_state)
    if state not in SUPPORTED_LOCAL_STATES:
        raise LeverPhaseBReviewedMaterialsError(
            "The application already entered an execution or terminal state"
        )

    target = persisted_supervised_target_metadata(job)
    if target.get("verified") is not True or target.get("blockers"):
        raise LeverPhaseBReviewedMaterialsError(
            "Current Lever application exact target identity is not verified"
        )

    site = str(target.get("site") or "").strip()
    posting_id = str(target.get("posting_id") or "").strip()
    region = str(target.get("region") or "").strip()
    application_url = canonical_lever_application_url(
        str(target.get("canonical_application_url") or job.url or "")
    )
    if not site or not posting_id or region not in {"global", "eu"}:
        raise LeverPhaseBReviewedMaterialsError(
            "Current Lever application target identity is incomplete"
        )

    candidate = {
        "review_id": f"current-lever-{application.id}",
        "application_id": f"current-lever-{application.id}",
        "employer": str(job.company or "").strip(),
        "role": str(job.title or "").strip(),
        "application_url": application_url,
        "site": site,
        "posting_id": posting_id,
        "region": region,
    }
    return candidate, application, job


def _fetch_current_hosted_posting(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    site = str(candidate["site"])
    posting_id = str(candidate["posting_id"])
    region = str(candidate.get("region") or "global")
    host = "jobs.eu.lever.co" if region == "eu" else "jobs.lever.co"
    hosted_url = f"https://{host}/{site}/{posting_id}"
    apply_url = f"{hosted_url}/apply"

    try:
        with httpx.Client(timeout=HOSTED_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(
                hosted_url,
                headers={
                    "User-Agent": "JobTomatik/2.0 supervised-material-preparation",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            response.raise_for_status()
    except Exception as exc:
        raise LeverPhaseBReviewedMaterialsError(
            "The exact hosted Lever posting could not be refreshed"
        ) from exc

    final_url = str(response.url)
    parsed = urlparse(final_url)
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != host
        or parsed.path.rstrip("/") != f"/{site}/{posting_id}"
        or parsed.query
        or parsed.fragment
    ):
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever posting redirected away from the exact selected target"
        )
    if "text/html" not in str(response.headers.get("content-type") or "").lower():
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever posting did not return HTML"
        )

    body = response.text
    role = _hosted_role(body)
    if not role:
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever posting did not expose an exact role title"
        )
    if " ".join(role.casefold().split()) != " ".join(str(candidate["role"]).casefold().split()):
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever role drifted from the selected target"
        )

    apply_path = f"/{site}/{posting_id}/apply"
    if apply_url not in body and apply_path not in body:
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever posting did not expose the exact apply route"
        )

    description = _clean_html_text(body)
    if len(description) < 200:
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever posting did not expose enough usable posting text"
        )

    return {
        "id": posting_id,
        "text": role,
        "categories": {},
        "description": description,
        "descriptionPlain": description,
        "hostedUrl": hosted_url,
        "applyUrl": apply_url,
        "lists": [],
        "_metadata_source": "lever_exact_hosted_page",
    }


def _posting_snapshot(
    candidate: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[Dict[str, Any], str]:
    import hashlib
    import json

    inspected = inspect_lever_posting(dict(payload))
    if not inspected.get("posting_metadata_certified"):
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever posting metadata failed certification"
        )
    if str(inspected.get("posting_id") or "") != str(candidate["posting_id"]):
        raise LeverPhaseBReviewedMaterialsError("The hosted Lever posting ID drifted")
    if str(inspected.get("site") or "").casefold() != str(candidate["site"]).casefold():
        raise LeverPhaseBReviewedMaterialsError("The hosted Lever site drifted")
    if str(inspected.get("region") or "").casefold() != str(candidate["region"]).casefold():
        raise LeverPhaseBReviewedMaterialsError("The hosted Lever region drifted")

    official_apply = canonical_lever_application_url(str(inspected.get("apply_url") or ""))
    if official_apply != candidate["application_url"]:
        raise LeverPhaseBReviewedMaterialsError("The hosted Lever apply URL drifted")
    if str(inspected.get("title") or "").strip().casefold() != str(candidate["role"]).strip().casefold():
        raise LeverPhaseBReviewedMaterialsError("The hosted Lever role drifted")

    description = str(payload.get("descriptionPlain") or "").strip()
    if not description:
        raise LeverPhaseBReviewedMaterialsError(
            "The hosted Lever posting has no usable plain-text description"
        )
    snapshot = {
        "posting_id": str(payload.get("id") or ""),
        "title": str(payload.get("text") or "").strip(),
        "categories": payload.get("categories") or {},
        "description_plain": description,
        "requirements_plain": None,
        "hosted_url": str(payload.get("hostedUrl") or "").strip(),
        "apply_url": official_apply,
        "site": str(candidate["site"]),
        "region": str(candidate["region"]),
        "source": str(payload.get("_metadata_source") or "lever_exact_hosted_page"),
    }
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return snapshot, digest


def prepare_current_lever_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
) -> Dict[str, Any]:
    """Generate source-backed materials and open an explicit review task."""

    resume_path = _required_resume_path(user)
    candidate, application, job = _current_candidate_records(
        db, user, application_id, lock=True
    )
    posting_snapshot, posting_sha256 = _posting_snapshot(
        candidate,
        _fetch_current_hosted_posting(candidate),
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
    evidence_digest = _evidence_digest(eligible)

    materials: list[ApplicationMaterial] = []
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
    _upsert_material_review_task(
        db,
        application,
        summary=(
            "Generated current Lever materials have source-validation blockers."
            if unique_critical
            else "Review both latest source-backed current Lever materials before preflight."
        ),
        details={
            "stage": REVIEW_STAGE,
            "review_id": candidate["review_id"],
            "material_ids": [material.id for material in materials],
            "material_versions": {
                material.material_type: material.version for material in materials
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


def show_current_lever_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
) -> Dict[str, Any]:
    """Read the exact latest review bundle without mutating application state."""

    candidate, application, job = _current_candidate_records(
        db, user, application_id, lock=False
    )
    materials: Dict[str, Any] = {}
    for material_type in MATERIAL_TYPES:
        material = _latest_material(db, application.id, material_type)
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
        "employer": candidate["employer"],
        "role": candidate["role"],
        "application_url": candidate["application_url"],
        "automation_state": normalize_state(application.automation_state),
        "open_review_count": _open_review_count(db, application.id),
        "posting_sha256": (job.raw_data or {}).get("lever_official_posting_sha256"),
        "materials": materials,
        "read_only": True,
    }


def review_current_lever_materials(
    db: Session,
    user: User,
    *,
    application_id: int,
    approved: bool,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Record the owner's explicit decision on the exact latest material bundle."""

    candidate, application, job = _current_candidate_records(
        db, user, application_id, lock=True
    )
    posting_sha256 = str(
        (job.raw_data or {}).get("lever_official_posting_sha256") or ""
    )
    if not posting_sha256:
        raise LeverPhaseBReviewedMaterialsError(
            "Prepare current Lever materials before reviewing them"
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
                "accepted_warning_count": len(material.warnings or []) if approved else 0,
            },
        }
        material.status = "verified" if approved else "needs_review"

    if not approved:
        _upsert_material_review_task(
            db,
            application,
            summary="The owner rejected the latest current Lever material bundle.",
            details={
                "stage": REVIEW_STAGE,
                "review_id": candidate["review_id"],
                "material_ids": [material.id for material in materials.values()],
                "review_eligible": not unique_critical,
                "critical_errors": unique_critical,
                "owner_rejected": True,
                "current_lever_application_id": application.id,
            },
            blocking_url=candidate["application_url"],
        )
        return {
            "application_id": application.id,
            "approved": False,
            "material_review_status": "rejected",
            "ready_for_fresh_preflight": False,
            "automation_state": normalize_state(application.automation_state),
            "open_review_count": _open_review_count(db, application.id),
            "approval_issued": False,
            "submission_queued": False,
            "runtime_flags_changed": False,
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
                "current_lever_application_id": application.id,
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
                    "current_lever_application_id": application.id,
                },
            )
        )

    db.flush()
    return {
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
        "runtime_flags_changed": False,
    }


__all__ = [
    "prepare_current_lever_materials",
    "show_current_lever_materials",
    "review_current_lever_materials",
]
