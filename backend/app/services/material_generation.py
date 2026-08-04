from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.material import (
    ApplicationMaterial,
    ApplicationMaterialEvidence,
    EvidenceUnit,
)
from app.models.user import User
from app.services.evidence_ledger import eligible_evidence_query, rebuild_user_evidence


GENERATOR_VERSION = "verified-material-v1"
SUPPORTED_MATERIAL_TYPES = {"cover_letter", "resume_summary"}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.#/-]{1,}", re.IGNORECASE)
STOP_WORDS = {
    "and", "the", "for", "with", "from", "that", "this", "your", "our", "you",
    "are", "will", "have", "has", "job", "role", "work", "team", "position",
    "candidate", "experience", "required", "preferred", "skills", "about", "into",
}
KIND_WEIGHT = {
    "achievement": 5.0,
    "employment": 4.5,
    "skill": 4.0,
    "credential": 3.5,
    "project": 3.5,
    "education": 3.0,
    "language": 3.0,
    "role": 2.5,
    "experience": 2.5,
    "summary": 2.0,
    "resume_fact": 1.5,
    "identity": 0.5,
    "location": 0.5,
}


class MaterialGenerationError(RuntimeError):
    pass


def _tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(str(value or ""))
        if token.casefold() not in STOP_WORDS and len(token) >= 3
    }


def _job_terms(job: Job) -> set[str]:
    terms = set()
    for value in (
        job.title,
        job.company,
        job.location,
        job.description,
        job.requirements,
        " ".join(job.skills or []),
    ):
        terms.update(_tokens(value))
    return terms


def _rank_evidence(units: Iterable[EvidenceUnit], job: Job) -> list[EvidenceUnit]:
    job_terms = _job_terms(job)
    ranked: list[tuple[float, EvidenceUnit]] = []
    for unit in units:
        unit_terms = _tokens(
            " ".join(
                filter(
                    None,
                    [unit.label, unit.statement, unit.organization, unit.role],
                )
            )
        )
        overlap = len(job_terms & unit_terms)
        score = KIND_WEIGHT.get(unit.kind, 1.0) + overlap * 2.0 + unit.confidence
        if unit.verification_status == "verified":
            score += 1.0
        elif unit.verification_status == "user_confirmed":
            score += 0.75
        ranked.append((score, unit))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [unit for _, unit in ranked]


def _first(units: Iterable[EvidenceUnit], kind: str) -> EvidenceUnit | None:
    return next((unit for unit in units if unit.kind == kind), None)


def _claim(
    text: str,
    evidence_units: Iterable[EvidenceUnit] = (),
    *,
    category: str,
    applicant_fact: bool = True,
) -> dict[str, Any]:
    units = list(evidence_units)
    return {
        "text": text.strip(),
        "category": category,
        "applicant_fact": applicant_fact,
        "evidence_unit_ids": [unit.id for unit in units],
        "evidence_hashes": [unit.source_hash for unit in units],
    }


def _identity_name(units: list[EvidenceUnit], user: User) -> tuple[str, EvidenceUnit | None]:
    name_unit = next(
        (
            unit
            for unit in units
            if unit.kind == "identity" and unit.label.casefold() == "full name"
        ),
        None,
    )
    return ((name_unit.statement if name_unit else (user.full_name or "")).strip(), name_unit)


def _cover_letter_content(
    user: User,
    job: Job,
    ranked: list[EvidenceUnit],
) -> tuple[str, list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    claims: list[dict[str, Any]] = []
    paragraphs: list[str] = ["Dear Hiring Manager,"]

    opening = f"I am applying for the {job.title} position at {job.company}."
    claims.append(_claim(opening, category="target_role", applicant_fact=False))
    opening_parts = [opening]

    current_role = _first(ranked, "role")
    years = _first(ranked, "experience")
    if current_role and years:
        sentence = (
            f"My documented profile identifies my current or most recent role as "
            f"{current_role.statement}, with {years.statement} years of experience."
        )
        opening_parts.append(sentence)
        claims.append(_claim(sentence, [current_role, years], category="career_summary"))
    elif current_role:
        sentence = (
            f"My documented profile identifies my current or most recent role as "
            f"{current_role.statement}."
        )
        opening_parts.append(sentence)
        claims.append(_claim(sentence, [current_role], category="career_summary"))
    elif years:
        sentence = f"My documented profile records {years.statement} years of experience."
        opening_parts.append(sentence)
        claims.append(_claim(sentence, [years], category="career_summary"))
    else:
        warnings.append("No source-backed current role or years-of-experience statement was available")
    paragraphs.append(" ".join(opening_parts))

    employment = [unit for unit in ranked if unit.kind == "employment"][:3]
    if employment:
        employment_lines = []
        for unit in employment:
            if unit.organization and unit.role:
                sentence = f"My employment record includes {unit.role} experience with {unit.organization}."
            elif unit.organization:
                sentence = f"My employment record includes experience with {unit.organization}."
            else:
                sentence = f"My employment record includes: {unit.statement}."
            employment_lines.append(sentence)
            claims.append(_claim(sentence, [unit], category="employment"))
        paragraphs.append(" ".join(employment_lines))
    else:
        warnings.append("No source-backed employment history was available")

    relevant = [
        unit
        for unit in ranked
        if unit.kind in {"achievement", "skill", "credential", "project", "language"}
    ][:6]
    if relevant:
        grouped: dict[str, list[EvidenceUnit]] = defaultdict(list)
        for unit in relevant:
            grouped[unit.kind].append(unit)

        detail_sentences: list[str] = []
        labels = {
            "achievement": "Source-backed highlights include",
            "skill": "Documented skills include",
            "credential": "Documented credentials include",
            "project": "Documented project evidence includes",
            "language": "Documented language capabilities include",
        }
        for kind in ("achievement", "skill", "credential", "project", "language"):
            group = grouped.get(kind) or []
            if not group:
                continue
            values = "; ".join(unit.statement for unit in group[:3])
            sentence = f"{labels[kind]} {values}."
            detail_sentences.append(sentence)
            claims.append(_claim(sentence, group[:3], category=kind))
        paragraphs.append(" ".join(detail_sentences))
    else:
        warnings.append("No source-backed achievements, skills, credentials, projects, or languages were available")

    alignment_terms = sorted(
        _job_terms(job)
        & set().union(*(_tokens(unit.statement) for unit in relevant))
    )[:6]
    if alignment_terms:
        sentence = (
            "These documented qualifications overlap with the posting in areas including "
            + ", ".join(alignment_terms)
            + "."
        )
        paragraphs.append(sentence)
        claims.append(
            _claim(
                sentence,
                relevant,
                category="job_alignment",
                applicant_fact=False,
            )
        )

    paragraphs.append(
        "Thank you for considering my application. I would welcome the opportunity to discuss the documented experience above in relation to your team’s needs."
    )

    name, name_unit = _identity_name(ranked, user)
    if name:
        signoff = f"Best regards,\n{name}"
        if name_unit:
            claims.append(_claim(name, [name_unit], category="identity"))
    else:
        signoff = "Best regards"
        warnings.append("No source-backed applicant name was available")
    paragraphs.append(signoff)
    return "\n\n".join(paragraphs).strip() + "\n", claims, warnings


def _resume_summary_content(
    user: User,
    job: Job,
    ranked: list[EvidenceUnit],
) -> tuple[str, list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    claims: list[dict[str, Any]] = []
    sections: list[str] = []

    name, name_unit = _identity_name(ranked, user)
    if name:
        sections.append(name)
        if name_unit:
            claims.append(_claim(name, [name_unit], category="identity"))
    else:
        warnings.append("No source-backed applicant name was available")

    sections.append(f"TARGET ROLE\n{job.title} | {job.company}")
    claims.append(
        _claim(
            f"{job.title} | {job.company}",
            category="target_role",
            applicant_fact=False,
        )
    )

    summary_units = [
        unit for unit in ranked if unit.kind in {"role", "experience", "summary"}
    ][:3]
    if summary_units:
        summary = " ".join(unit.statement.rstrip(".") + "." for unit in summary_units)
        sections.append(f"PROFESSIONAL SUMMARY\n{summary}")
        claims.append(_claim(summary, summary_units, category="career_summary"))
    else:
        warnings.append("No source-backed professional summary evidence was available")

    employment = [unit for unit in ranked if unit.kind == "employment"][:5]
    if employment:
        lines = [f"• {unit.statement}" for unit in employment]
        sections.append("RELEVANT EXPERIENCE\n" + "\n".join(lines))
        for unit in employment:
            claims.append(_claim(unit.statement, [unit], category="employment"))
    else:
        warnings.append("No source-backed employment evidence was available")

    skills = [unit for unit in ranked if unit.kind == "skill"][:12]
    if skills:
        line = ", ".join(unit.statement for unit in skills)
        sections.append(f"CORE SKILLS\n{line}")
        claims.append(_claim(line, skills, category="skill"))
    else:
        warnings.append("No source-backed skill evidence was available")

    for heading, kinds, category in (
        ("SELECTED ACHIEVEMENTS", {"achievement"}, "achievement"),
        ("EDUCATION AND CREDENTIALS", {"education", "credential"}, "credential"),
        ("PROJECTS", {"project"}, "project"),
        ("LANGUAGES", {"language"}, "language"),
    ):
        units = [unit for unit in ranked if unit.kind in kinds][:5]
        if not units:
            continue
        sections.append(heading + "\n" + "\n".join(f"• {unit.statement}" for unit in units))
        for unit in units:
            claims.append(_claim(unit.statement, [unit], category=category))

    return "\n\n".join(sections).strip() + "\n", claims, warnings


def validate_claims(
    claims: list[dict[str, Any]],
    eligible_units: Iterable[EvidenceUnit],
) -> list[str]:
    warnings: list[str] = []
    unit_by_id = {unit.id: unit for unit in eligible_units}
    for index, claim in enumerate(claims):
        ids = claim.get("evidence_unit_ids") or []
        if claim.get("applicant_fact", True) and not ids:
            warnings.append(f"Claim {index} is an applicant fact without evidence")
            continue
        missing = [unit_id for unit_id in ids if unit_id not in unit_by_id]
        if missing:
            warnings.append(f"Claim {index} references unavailable evidence units: {missing}")
            continue
        expected_hashes = [unit_by_id[unit_id].source_hash for unit_id in ids]
        if expected_hashes != (claim.get("evidence_hashes") or []):
            warnings.append(f"Claim {index} evidence hashes do not match the ledger")
    return warnings


def _next_version(db: Session, application_id: int, material_type: str) -> int:
    current = (
        db.query(func.max(ApplicationMaterial.version))
        .filter(
            ApplicationMaterial.application_id == application_id,
            ApplicationMaterial.material_type == material_type,
        )
        .scalar()
    )
    return int(current or 0) + 1


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
        raise MaterialGenerationError(f"Unsupported material type: {material_type}")

    rebuild_result = rebuild_user_evidence(db, user) if rebuild_evidence else None
    eligible = eligible_evidence_query(db, user.id).all()
    ranked = _rank_evidence(eligible, job)

    if material_type == "cover_letter":
        content, claims, warnings = _cover_letter_content(user, job, ranked)
    else:
        content, claims, warnings = _resume_summary_content(user, job, ranked)

    warnings.extend(validate_claims(claims, eligible))
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
    version = _next_version(db, application.id, material_type)
    used_ids = sorted(
        {
            unit_id
            for claim in claims
            for unit_id in (claim.get("evidence_unit_ids") or [])
        }
    )
    unit_by_id = {unit.id: unit for unit in eligible}
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
        },
        generator_version=GENERATOR_VERSION,
        supersedes_material_id=previous.id if previous else None,
    )
    db.add(material)
    db.flush()

    claim_indexes_by_unit: dict[int, list[int]] = defaultdict(list)
    for claim_index, claim in enumerate(claims):
        for unit_id in claim.get("evidence_unit_ids") or []:
            claim_indexes_by_unit[unit_id].append(claim_index)
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
