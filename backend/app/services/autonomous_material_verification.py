"""Day 31 deterministic verification for autonomous application materials.

The existing material generator is source-mapped and evidence-conservative. This layer
adds document identity, canonical resume selection, confidence thresholds, deterministic
content hashes, and stale-material verification for the autonomous preparation path.
It never invents applicant facts and never changes submission authorization.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.user import User
from app.services.evidence_ledger import eligible_evidence_query
from app.services.material_generation import generate_application_material, validate_claims


DAY31_MATERIAL_POLICY_VERSION = "autonomous-material-verification-v1"
MIN_AUTONOMOUS_CLAIM_CONFIDENCE = 0.80


class MaterialVerificationError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def text_sha256(value: str) -> str:
    return _sha256_bytes(str(value or "").encode("utf-8"))


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_path(value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except Exception:
        return Path(raw).expanduser()


def inspect_resume_selection(application: Application, user: User) -> dict[str, Any]:
    """Resolve one canonical resume without silently accepting conflicting paths."""

    canonical = _normalized_path(user.resume_path)
    selected = _normalized_path(application.resume_path)
    blockers: list[str] = []

    if canonical is None:
        blockers.append("canonical_resume_missing")
        return {
            "status": "needs_review",
            "blockers": blockers,
            "path": None,
            "filename": None,
            "sha256": None,
            "size_bytes": None,
            "mtime_ns": None,
        }

    if selected is not None and selected != canonical:
        blockers.append("conflicting_resume_selection")

    if not canonical.is_file():
        blockers.append("canonical_resume_file_missing")
        digest = None
        size_bytes = None
        mtime_ns = None
    else:
        try:
            stat = canonical.stat()
            digest = file_sha256(canonical)
            size_bytes = int(stat.st_size)
            mtime_ns = int(stat.st_mtime_ns)
        except OSError:
            blockers.append("canonical_resume_unreadable")
            digest = None
            size_bytes = None
            mtime_ns = None

    return {
        "status": "verified" if not blockers else "needs_review",
        "blockers": sorted(set(blockers)),
        "path": str(canonical),
        "filename": str(user.resume_filename or canonical.name),
        "sha256": digest,
        "size_bytes": size_bytes,
        "mtime_ns": mtime_ns,
    }


def _public_resume_snapshot(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": selection.get("status"),
        "filename": selection.get("filename"),
        "sha256": selection.get("sha256"),
        "size_bytes": selection.get("size_bytes"),
        "mtime_ns": selection.get("mtime_ns"),
        "blockers": list(selection.get("blockers") or []),
    }


def _used_evidence_units(
    material: ApplicationMaterial,
    eligible: list[EvidenceUnit],
) -> list[EvidenceUnit]:
    ids = {
        int(unit_id)
        for claim in list(material.claims or [])
        if claim.get("applicant_fact", True)
        for unit_id in (claim.get("evidence_unit_ids") or [])
    }
    return [unit for unit in eligible if unit.id in ids]


def _critical_claim_blockers(
    material: ApplicationMaterial,
    eligible: list[EvidenceUnit],
) -> tuple[list[str], list[str], float | None]:
    blockers: list[str] = []
    advisories = list(material.warnings or [])

    validation_errors = validate_claims(list(material.claims or []), eligible)
    if validation_errors:
        blockers.append("unsupported_or_drifted_claim")
        advisories.extend(validation_errors)

    substantive = [
        claim
        for claim in list(material.claims or [])
        if claim.get("applicant_fact", True)
        and claim.get("category") not in {"identity"}
        and claim.get("evidence_unit_ids")
    ]
    if not substantive:
        blockers.append("substantive_applicant_evidence_missing")

    used = _used_evidence_units(material, eligible)
    min_confidence = min((float(unit.confidence) for unit in used), default=None)
    low_confidence = [
        unit.id
        for unit in used
        if float(unit.confidence) < MIN_AUTONOMOUS_CLAIM_CONFIDENCE
    ]
    if low_confidence:
        blockers.append("applicant_evidence_confidence_low")
        advisories.append(
            "Applicant claims reference evidence below the autonomous confidence threshold: "
            + ", ".join(str(unit_id) for unit_id in sorted(low_confidence))
        )

    return sorted(set(blockers)), sorted(set(advisories)), min_confidence


def stamp_material_verification(
    db: Session,
    material: ApplicationMaterial,
    application: Application,
    user: User,
) -> dict[str, Any]:
    """Bind a generated material to exact content, claims, evidence, and resume bytes."""

    eligible = eligible_evidence_query(db, int(user.id)).all()
    claim_blockers, advisories, min_confidence = _critical_claim_blockers(
        material,
        eligible,
    )
    resume = inspect_resume_selection(application, user)
    blockers = sorted(set(claim_blockers + list(resume.get("blockers") or [])))

    if not resume.get("blockers") and resume.get("path"):
        application.resume_path = str(resume["path"])

    content_hash = text_sha256(material.content)
    claims_hash = canonical_json_sha256(list(material.claims or []))
    evidence_hash = canonical_json_sha256(
        [
            {
                "id": unit.id,
                "source_hash": unit.source_hash,
                "source_type": unit.source_type,
                "source_ref": unit.source_ref,
                "confidence": float(unit.confidence),
                "verification_status": unit.verification_status,
            }
            for unit in sorted(_used_evidence_units(material, eligible), key=lambda item: item.id)
        ]
    )

    verification = {
        "policy_version": DAY31_MATERIAL_POLICY_VERSION,
        "content_sha256": content_hash,
        "claims_sha256": claims_hash,
        "evidence_sha256": evidence_hash,
        "resume": _public_resume_snapshot(resume),
        "minimum_used_evidence_confidence": min_confidence,
        "minimum_required_evidence_confidence": MIN_AUTONOMOUS_CLAIM_CONFIDENCE,
        "blockers": blockers,
        "advisories": advisories,
        "requires_manual_review": bool(blockers),
    }
    verification["verification_sha256"] = canonical_json_sha256(verification)

    snapshot = dict(material.source_snapshot or {})
    snapshot["day31_material_verification"] = verification
    material.source_snapshot = snapshot
    material.status = "needs_review" if blockers else "verified"
    db.flush()
    return verification


def verify_material_integrity(
    db: Session,
    material: ApplicationMaterial,
    application: Application,
    user: User,
) -> dict[str, Any]:
    """Re-check a stamped material and fail closed on document/content/evidence drift."""

    snapshot = dict(material.source_snapshot or {})
    stamped = dict(snapshot.get("day31_material_verification") or {})
    blockers: list[str] = []
    if not stamped:
        return {
            "policy_version": DAY31_MATERIAL_POLICY_VERSION,
            "valid": False,
            "requires_manual_review": True,
            "blockers": ["material_verification_snapshot_missing"],
        }

    if text_sha256(material.content) != stamped.get("content_sha256"):
        blockers.append("material_content_changed")
    if canonical_json_sha256(list(material.claims or [])) != stamped.get("claims_sha256"):
        blockers.append("material_claims_changed")

    eligible = eligible_evidence_query(db, int(user.id)).all()
    validation_errors = validate_claims(list(material.claims or []), eligible)
    if validation_errors:
        blockers.append("material_evidence_drift")

    used_hash = canonical_json_sha256(
        [
            {
                "id": unit.id,
                "source_hash": unit.source_hash,
                "source_type": unit.source_type,
                "source_ref": unit.source_ref,
                "confidence": float(unit.confidence),
                "verification_status": unit.verification_status,
            }
            for unit in sorted(_used_evidence_units(material, eligible), key=lambda item: item.id)
        ]
    )
    if used_hash != stamped.get("evidence_sha256"):
        blockers.append("material_evidence_snapshot_changed")

    resume = inspect_resume_selection(application, user)
    blockers.extend(list(resume.get("blockers") or []))
    stamped_resume = dict(stamped.get("resume") or {})
    if resume.get("sha256") != stamped_resume.get("sha256"):
        blockers.append("resume_document_changed")
    if resume.get("filename") != stamped_resume.get("filename"):
        blockers.append("resume_selection_changed")

    blockers = sorted(set(blockers))
    return {
        "policy_version": DAY31_MATERIAL_POLICY_VERSION,
        "valid": not blockers,
        "requires_manual_review": bool(blockers),
        "blockers": blockers,
        "content_sha256": text_sha256(material.content),
        "claims_sha256": canonical_json_sha256(list(material.claims or [])),
        "resume": _public_resume_snapshot(resume),
    }


def generate_autonomy_verified_material(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    material_type: str = "cover_letter",
    rebuild_evidence: bool = True,
) -> tuple[ApplicationMaterial, dict[str, Any]]:
    material = generate_application_material(
        db,
        application,
        user,
        job,
        material_type=material_type,
        rebuild_evidence=rebuild_evidence,
    )
    verification = stamp_material_verification(db, material, application, user)
    return material, verification
