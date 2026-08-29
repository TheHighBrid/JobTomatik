from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.material import (
    ApplicationMaterial,
    ApplicationMaterialEvidence,
    EvidenceUnit,
)
from app.models.user import User
from app.services import material_generation as base
from app.services.evidence_ledger import eligible_evidence_query, rebuild_user_evidence


GENERATOR_VERSION = "verified-material-v4"
SUPPORTED_MATERIAL_TYPES = base.SUPPORTED_MATERIAL_TYPES

SECTION_HEADING_TERMS = {
    "achievement",
    "achievements",
    "certification",
    "certifications",
    "credential",
    "credentials",
    "education",
    "employment",
    "experience",
    "history",
    "language",
    "languages",
    "profile",
    "project",
    "projects",
    "qualification",
    "qualifications",
    "skill",
    "skills",
    "summary",
    "technical",
}

HIGH_SUPPORT_SIGNALS = {
    "care",
    "channel",
    "channels",
    "client",
    "clients",
    "communication",
    "communications",
    "customer",
    "customers",
    "digital",
    "help",
    "helpdesk",
    "issue",
    "issues",
    "network",
    "networking",
    "resolution",
    "resolve",
    "resolved",
    "service",
    "services",
    "software",
    "support",
    "supported",
    "supporting",
    "system",
    "systems",
    "technical",
    "ticket",
    "tickets",
    "troubleshoot",
    "troubleshooting",
}

IGNORED_ALIGNMENT_TERMS = set(base.GENERIC_ALIGNMENT_TERMS) | {
    "account",
    "accounts",
    "canada",
    "fullscript",
    "ottawa",
}

SUPPORT_FRIENDLY_SKILLS = {
    "ai tools": 35,
    "bilingual": 100,
    "data analysis": 45,
    "de-escalation": 75,
    "debian": 70,
    "linux": 80,
    "microsoft office": 90,
    "time management": 55,
}


class MaterialGenerationV4Error(base.MaterialGenerationError):
    pass


def _clean(value: Any) -> str:
    return base._clean_material_statement(value)


def _looks_like_section_heading_text(value: Any) -> bool:
    text = _clean(value)
    if not text or base.YEAR_RE.search(text) or "|" in text:
        return False
    if re.search(r"[.!?]$", text):
        return False

    words = re.findall(r"[A-Za-z]+", text)
    if not 1 <= len(words) <= 8:
        return False
    lowered = {word.casefold() for word in words}
    if not (lowered & SECTION_HEADING_TERMS):
        return False

    letters = "".join(char for char in text if char.isalpha())
    all_caps = bool(letters) and letters.upper() == letters
    heading_vocab_only = all(
        word.casefold() in SECTION_HEADING_TERMS or word.casefold() in {"and", "of"}
        for word in words
    )
    return all_caps or heading_vocab_only


def _unit_text(unit: EvidenceUnit) -> str:
    return " ".join(
        filter(
            None,
            [
                _clean(unit.label),
                _clean(unit.statement),
                _clean(unit.organization),
                _clean(unit.role),
            ],
        )
    )


def _job_overlap_count(unit: EvidenceUnit, job: Job) -> int:
    job_terms = base._job_terms(job) - IGNORED_ALIGNMENT_TERMS
    unit_terms = base._tokens(_unit_text(unit)) - IGNORED_ALIGNMENT_TERMS
    return len(job_terms & unit_terms)


def _support_signal_count(value: Any) -> int:
    return len(base._tokens(value) & HIGH_SUPPORT_SIGNALS)


def _role_is_relevant(unit: EvidenceUnit, job: Job) -> bool:
    return _support_signal_count(_unit_text(unit)) > 0 or _job_overlap_count(unit, job) >= 2


def _employment_is_relevant(unit: EvidenceUnit, job: Job) -> bool:
    if _looks_like_section_heading_text(unit.statement):
        return False
    if base._evidence_fragment_reason(unit):
        return False

    text = _unit_text(unit)
    high_signals = _support_signal_count(text)
    overlap = _job_overlap_count(unit, job)

    if unit.role or unit.organization or base._looks_like_employment_header(unit):
        return high_signals > 0 or overlap >= 2
    return high_signals > 0 or overlap >= 2


def _skill_priority(unit: EvidenceUnit, job: Job) -> int | None:
    display = base._display_skill(unit.statement).casefold()
    overlap = _job_overlap_count(unit, job)
    curated = SUPPORT_FRIENDLY_SKILLS.get(display)
    if overlap <= 0 and curated is None:
        return None
    return overlap * 100 + int(curated or 0)


def _curated_ranked(units: Iterable[EvidenceUnit], job: Job) -> list[EvidenceUnit]:
    ranked = base._rank_evidence(units, job)
    source_order = {unit.id: index for index, unit in enumerate(ranked)}
    kept: list[tuple[int, int, EvidenceUnit]] = []

    for unit in ranked:
        if _looks_like_section_heading_text(unit.statement):
            continue
        if base._evidence_fragment_reason(unit):
            continue

        priority = 0
        if unit.kind == "role":
            if not _role_is_relevant(unit, job):
                continue
            priority = 500 + _job_overlap_count(unit, job) * 100 + _support_signal_count(_unit_text(unit)) * 25
        elif unit.kind == "employment":
            if not _employment_is_relevant(unit, job):
                continue
            priority = 700 + _job_overlap_count(unit, job) * 100 + _support_signal_count(_unit_text(unit)) * 25
        elif unit.kind == "skill":
            skill_priority = _skill_priority(unit, job)
            if skill_priority is None:
                continue
            priority = 600 + skill_priority
        elif unit.kind in base.FRAGMENT_SENSITIVE_KINDS and not base._usable_narrative_unit(unit):
            continue

        kept.append((-priority, source_order[unit.id], unit))

    kept.sort(key=lambda item: (item[0], item[1]))
    return [unit for _, _, unit in kept]


def _quality_warnings(
    content: str,
    claims: list[dict[str, Any]],
    job: Job,
    unit_by_id: dict[int, EvidenceUnit],
) -> list[str]:
    warnings: list[str] = []

    for index, claim in enumerate(claims):
        text = str(claim.get("text") or "").strip()
        category = str(claim.get("category") or "")
        if _looks_like_section_heading_text(text):
            warnings.append(f"Claim {index} is a résumé section heading, not applicant evidence")

        ids = [int(value) for value in (claim.get("evidence_unit_ids") or [])]
        for unit_id in ids:
            unit = unit_by_id.get(unit_id)
            if unit is None:
                continue
            if _looks_like_section_heading_text(unit.statement):
                warnings.append(
                    f"Claim {index} references résumé section-heading evidence unit {unit_id}"
                )
            if category in {"career_summary", "employment", "job_alignment"}:
                if unit.kind == "role" and not _role_is_relevant(unit, job):
                    warnings.append(
                        f"Claim {index} references a role without material target-role alignment: evidence unit {unit_id}"
                    )
                if unit.kind == "employment" and not _employment_is_relevant(unit, job):
                    warnings.append(
                        f"Claim {index} references employment evidence without material target-role alignment: evidence unit {unit_id}"
                    )

    content_lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    for line in content_lines:
        if _looks_like_section_heading_text(line) and line not in {
            "TARGET ROLE",
            "PROFESSIONAL SUMMARY",
            "RELEVANT EXPERIENCE",
            "CORE SKILLS",
            "SELECTED ACHIEVEMENTS",
            "EDUCATION AND CREDENTIALS",
            "PROJECTS",
            "LANGUAGES",
        }:
            warnings.append(f"Generated material contains an unexpected résumé section heading: {line}")

    return warnings


def generate_application_material(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    material_type: str = "cover_letter",
    rebuild_evidence: bool = True,
) -> ApplicationMaterial:
    if material_type not in SUPPORTED_MATERIAL_TYPES:
        raise MaterialGenerationV4Error(f"Unsupported material type: {material_type}")

    rebuild_result = rebuild_user_evidence(db, user) if rebuild_evidence else None
    eligible = eligible_evidence_query(db, user.id).all()
    ranked = _curated_ranked(eligible, job)

    if material_type == "cover_letter":
        content, claims, warnings = base._cover_letter_content(user, job, ranked)
    else:
        content, claims, warnings = base._resume_summary_content(user, job, ranked)

    warnings.extend(base.validate_claims(claims, eligible))
    unit_by_id = {unit.id: unit for unit in eligible}
    warnings.extend(_quality_warnings(content, claims, job, unit_by_id))

    substantive = [
        claim
        for claim in claims
        if claim.get("applicant_fact", True)
        and claim.get("category") not in {"identity"}
        and claim.get("evidence_unit_ids")
    ]
    if not substantive:
        warnings.append("No substantive applicant claim could be supported by active evidence")

    status = "verified" if not warnings else "needs_review"
    previous = (
        db.query(ApplicationMaterial)
        .filter(
            ApplicationMaterial.application_id == application.id,
            ApplicationMaterial.material_type == material_type,
        )
        .order_by(ApplicationMaterial.version.desc())
        .first()
    )
    version = base._next_version(db, application.id, material_type)
    used_ids = sorted(
        {
            unit_id
            for claim in claims
            for unit_id in (claim.get("evidence_unit_ids") or [])
        }
    )

    material = ApplicationMaterial(
        user_id=user.id,
        application_id=application.id,
        material_type=material_type,
        version=version,
        status=status,
        content=content,
        claims=claims,
        warnings=sorted(set(warnings)),
        source_snapshot={
            "job": {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "url": job.url,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            },
            "evidence_units": [
                {
                    "id": unit_id,
                    "source_hash": unit_by_id[unit_id].source_hash,
                    "source_type": unit_by_id[unit_id].source_type,
                    "source_ref": unit_by_id[unit_id].source_ref,
                    "verification_status": unit_by_id[unit_id].verification_status,
                }
                for unit_id in used_ids
                if unit_id in unit_by_id
            ],
            "evidence_rebuild": rebuild_result,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "quality_policy": "target-aligned-evidence-v1",
        },
        generator_version=GENERATOR_VERSION,
        supersedes_material_id=previous.id if previous else None,
    )
    db.add(material)
    db.flush()

    claim_indexes_by_unit: dict[int, list[int]] = defaultdict(list)
    for claim_index, claim in enumerate(claims):
        for unit_id in claim.get("evidence_unit_ids") or []:
            claim_indexes_by_unit[int(unit_id)].append(claim_index)

    now = datetime.now(timezone.utc)
    for unit_id, claim_indexes in claim_indexes_by_unit.items():
        if unit_id not in unit_by_id:
            continue
        db.add(
            ApplicationMaterialEvidence(
                material_id=material.id,
                evidence_unit_id=unit_id,
                usage="supporting_claim",
                claim_indexes=claim_indexes,
            )
        )
        unit_by_id[unit_id].last_used_at = now

    if material_type == "cover_letter":
        application.cover_letter = content
    elif material_type == "resume_summary":
        application.resume_path = application.resume_path or user.resume_path

    db.flush()
    return material
