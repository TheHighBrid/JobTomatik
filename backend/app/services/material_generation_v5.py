from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.material import ApplicationMaterial, ApplicationMaterialEvidence, EvidenceUnit
from app.models.user import User
from app.services import material_generation as base
from app.services import material_generation_v4 as v4
from app.services.evidence_ledger import eligible_evidence_query, rebuild_user_evidence


GENERATOR_VERSION = "verified-material-v5"
SUPPORTED_MATERIAL_TYPES = base.SUPPORTED_MATERIAL_TYPES

SKILL_ORDER = {
    "bilingual": 100,
    "linux": 95,
    "debian": 90,
    "ai tools": 85,
    "data analysis": 80,
    "microsoft office": 75,
    "de-escalation": 60,
    "time management": 40,
}

TECHNICAL_SKILL_LABELS = {
    "ai tools",
    "data analysis",
    "debian",
    "linux",
    "microsoft office",
}

V5_STRUCTURAL_HEADINGS = {
    "EMPLOYMENT HISTORY",
    "RELEVANT SUPPORT EXPERIENCE",
}


class MaterialGenerationV5Error(base.MaterialGenerationError):
    pass


def _clean(value: Any) -> str:
    return base._clean_material_statement(value)


def _skill_units(ranked: Iterable[EvidenceUnit], job: Job, *, limit: int = 6) -> list[EvidenceUnit]:
    skills = [unit for unit in ranked if unit.kind == "skill" and base._usable_narrative_unit(unit)]
    scored: list[tuple[int, int, EvidenceUnit]] = []
    for index, unit in enumerate(skills):
        display = base._display_skill(unit.statement).casefold()
        priority = SKILL_ORDER.get(display)
        if priority is None:
            v4_priority = v4._skill_priority(unit, job)
            if v4_priority is None:
                continue
            priority = max(1, v4_priority)
        scored.append((-priority, index, unit))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [unit for _, _, unit in scored[:limit]]


def _technical_skill_units(skills: Iterable[EvidenceUnit]) -> list[EvidenceUnit]:
    return [
        unit
        for unit in skills
        if base._display_skill(unit.statement).casefold() in TECHNICAL_SKILL_LABELS
    ]


def _employment_units(ranked: Iterable[EvidenceUnit]) -> tuple[list[EvidenceUnit], list[EvidenceUnit]]:
    employment = [unit for unit in ranked if unit.kind == "employment" and base._usable_narrative_unit(unit)]
    headers = [unit for unit in employment if base._looks_like_employment_header(unit)]
    details = [unit for unit in employment if not base._looks_like_employment_header(unit)]
    return headers, details


def _support_details(details: Iterable[EvidenceUnit], job: Job, *, limit: int = 1) -> list[EvidenceUnit]:
    ranked: list[tuple[int, int, EvidenceUnit]] = []
    for index, unit in enumerate(details):
        support = v4._support_signal_count(v4._unit_text(unit))
        overlap = v4._job_overlap_count(unit, job)
        ranked.append((-(support * 100 + overlap * 50), index, unit))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [unit for _, _, unit in ranked[:limit]]


def _header_support_phrase(header: EvidenceUnit | None) -> str:
    if header is None:
        return "documented professional experience"
    text = _clean(header.statement).casefold()
    if "bilingual" in text and ("customer" in text or "care" in text or "support" in text):
        return "bilingual customer care experience"
    if "customer" in text or "care" in text or "support" in text:
        return "customer support experience"
    return "documented professional experience"


def _header_establishes_support(header: EvidenceUnit | None) -> bool:
    if header is None:
        return False
    text = _clean(header.statement).casefold()
    return any(term in text for term in ("customer", "care", "support"))


def _paraphrase_support_detail(unit: EvidenceUnit) -> str:
    text = _clean(unit.statement)
    lowered = text.casefold()
    explicitly_client_support = bool(
        re.search(r"\b(?:support(?:ed|ing)?|assist(?:ed|ing)?|help(?:ed|ing)?)\b", lowered)
        and re.search(r"\b(?:client|clients|customer|customers)\b", lowered)
    )
    if explicitly_client_support and "multiple communication channels" in lowered:
        return "Supported clients across multiple communication channels."

    # Customer-education statements are preserved rather than semantically widened.
    # Evidence validation proves the source line exists, not that a broader paraphrase
    # is entailed by it.
    if re.search(r"\beducat(?:e|ed|ing)\b", lowered) and re.search(
        r"\b(?:client|clients|customer|customers)\b", lowered
    ):
        return base._as_sentence(text)

    return base._as_sentence(text)


def _job_focus_items(job: Job) -> list[str]:
    text = " ".join(
        _clean(value).casefold()
        for value in (
            job.title,
            job.description,
            job.requirements,
            " ".join(job.skills or []),
        )
        if value
    )
    items: list[str] = []
    if re.search(r"\b(?:investigat|troubleshoot|reproduc|technical issue|technical issues)\w*", text):
        items.append("issue investigation")
    if re.search(r"\b(?:document|documentation|case notes?|repro steps?|logs?)\w*", text):
        items.append("documentation")
    if re.search(r"\b(?:cross-functional|engineering|partner(?:ing)? with|collaborat)\w*", text):
        items.append("cross-functional collaboration")
    if re.search(r"\b(?:api|apis|integration|integrations|web technolog|web technologies)\w*", text):
        items.append("technical troubleshooting")
    return items[:3]


def _joined_focus(items: list[str]) -> str:
    if not items:
        return "the responsibilities described in the posting"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{items[0]}, {items[1]}, and {items[2]}"


def _target_alignment_sentence(job: Job) -> str:
    focus = _joined_focus(_job_focus_items(job))
    return (
        "I am interested in applying that combination of customer communication and technical literacy "
        f"to {job.company}'s {job.title} role, with particular interest in {focus}."
    )


def _cover_letter_content(
    user: User,
    job: Job,
    ranked: list[EvidenceUnit],
) -> tuple[str, list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    claims: list[dict[str, Any]] = []
    paragraphs = ["Dear Hiring Manager,"]

    opening = f"I am applying for the {job.title} position at {job.company}."
    paragraphs.append(opening)
    claims.append(base._claim(opening, category="target_role", applicant_fact=False))

    headers, details = _employment_units(ranked)
    support_details = _support_details(details, job, limit=1)
    skills = _skill_units(ranked, job, limit=6)
    technical_skills = _technical_skill_units(skills)

    background_parts: list[str] = []
    background_units: list[EvidenceUnit] = []
    if headers:
        background_parts.append(f"My background includes {_header_support_phrase(headers[0])}")
        background_units.append(headers[0])
    elif support_details:
        background_parts.append("My background includes customer-facing support experience")
        background_units.extend(support_details[:1])

    if technical_skills:
        skill_text = ", ".join(base._display_skill(unit.statement) for unit in technical_skills)
        if background_parts:
            background_parts[-1] += f" and technical skills in {skill_text}."
        else:
            background_parts.append(f"My documented technical skills include {skill_text}.")
        background_units.extend(technical_skills)
    elif background_parts:
        background_parts[-1] += "."

    if background_parts:
        background = " ".join(background_parts)
        paragraphs.append(background)
        claims.append(base._claim(background, background_units, category="career_summary"))

    if support_details:
        detail_text = " ".join(_paraphrase_support_detail(unit) for unit in support_details)
        paragraphs.append(detail_text)
        claims.append(base._claim(detail_text, support_details, category="job_alignment"))
    else:
        warnings.append("No source-backed customer-support detail was available for the cover letter")

    alignment = _target_alignment_sentence(job)
    paragraphs.append(alignment)
    claims.append(base._claim(alignment, category="target_alignment", applicant_fact=False))

    paragraphs.append(
        "Thank you for considering my application. I would welcome the opportunity to discuss how my experience could support your team and customers."
    )

    name, name_unit = base._identity_name(ranked, user)
    if name:
        paragraphs.append(f"Best regards,\n{name}")
        if name_unit:
            claims.append(base._claim(name, [name_unit], category="identity"))
    else:
        paragraphs.append("Best regards")
        warnings.append("No source-backed applicant name was available")

    return "\n\n".join(paragraphs).strip() + "\n", claims, warnings


def _resume_summary_content(
    user: User,
    job: Job,
    ranked: list[EvidenceUnit],
) -> tuple[str, list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    claims: list[dict[str, Any]] = []
    sections: list[str] = []

    name, name_unit = base._identity_name(ranked, user)
    if name:
        sections.append(name)
        if name_unit:
            claims.append(base._claim(name, [name_unit], category="identity"))
    else:
        warnings.append("No source-backed applicant name was available")

    target = f"{job.title} | {job.company}"
    sections.append(f"TARGET ROLE\n{target}")
    claims.append(base._claim(target, category="target_role", applicant_fact=False))

    headers, details = _employment_units(ranked)
    support_details = _support_details(details, job, limit=1)
    skills = _skill_units(ranked, job, limit=6)
    technical_skills = _technical_skill_units(skills)

    summary_units: list[EvidenceUnit] = []
    summary_parts: list[str] = []
    if headers and _header_establishes_support(headers[0]):
        summary_parts.append(
            f"Customer-facing support professional with {_header_support_phrase(headers[0])}"
        )
        summary_units.append(headers[0])
    elif support_details:
        summary_parts.append("Customer-facing support professional with documented professional experience")
        summary_units.extend(support_details[:1])
        if headers:
            summary_units.append(headers[0])
    elif headers:
        summary_parts.append("Professional with documented employment experience")
        summary_units.append(headers[0])
    else:
        summary_parts.append("Professional")

    if technical_skills:
        skill_text = ", ".join(base._display_skill(unit.statement) for unit in technical_skills)
        summary_parts[-1] += f" and documented technical skills in {skill_text}."
        summary_units.extend(technical_skills)
    else:
        summary_parts[-1] += "."

    if support_details:
        summary_parts.append(" ".join(_paraphrase_support_detail(unit) for unit in support_details))
        summary_units.extend(unit for unit in support_details if unit not in summary_units)

    summary = " ".join(summary_parts)
    sections.append(f"PROFESSIONAL SUMMARY\n{summary}")
    claims.append(base._claim(summary, summary_units, category="career_summary"))

    if headers:
        header_lines = [f"• {_clean(unit.statement)}" for unit in headers[:2]]
        sections.append("EMPLOYMENT HISTORY\n" + "\n".join(header_lines))
        for unit in headers[:2]:
            claims.append(base._claim(_clean(unit.statement), [unit], category="employment"))

    if support_details:
        support_lines = [f"• {_paraphrase_support_detail(unit).rstrip('.')}" for unit in support_details]
        sections.append("RELEVANT SUPPORT EXPERIENCE\n" + "\n".join(support_lines))
        for unit, line in zip(support_details, support_lines):
            claims.append(base._claim(line.removeprefix("• "), [unit], category="employment"))

    if not headers and not support_details:
        warnings.append("No source-backed relevant employment evidence was available")

    if skills:
        line = ", ".join(base._display_skill(unit.statement) for unit in skills)
        sections.append(f"CORE SKILLS\n{line}")
        claims.append(base._claim(line, skills, category="skill"))
    else:
        warnings.append("No source-backed target-relevant skill evidence was available")

    return "\n\n".join(sections).strip() + "\n", claims, warnings


def _v4_compatible_quality_warnings(
    content: str,
    claims: list[dict[str, Any]],
    job: Job,
    unit_by_id: dict[int, EvidenceUnit],
) -> list[str]:
    warnings = v4._quality_warnings(content, claims, job, unit_by_id)
    allowed = {
        "Generated material contains an unexpected résumé section heading: " + heading
        for heading in V5_STRUCTURAL_HEADINGS
        if f"\n{heading}\n" in f"\n{content}"
    }
    return [warning for warning in warnings if warning not in allowed]


def _v5_quality_warnings(content: str, material_type: str) -> list[str]:
    warnings: list[str] = []
    if "EDUCATION & TECHNICAL SKILLS" in content:
        warnings.append("Generated material leaked a résumé section heading")
    if material_type == "cover_letter" and "My documented experience relevant to this role includes:" in content:
        warnings.append("Cover letter used the legacy evidence-dump rendering pattern")
    if "technical skills in Bilingual" in content:
        warnings.append("Bilingual capability was mislabeled as a technical skill")
    if "technical skills in De-escalation" in content or "technical skills in Time Management" in content:
        warnings.append("Interpersonal or time-management skill was mislabeled as technical")
    if material_type == "resume_summary" and "RELEVANT EXPERIENCE\n" in content:
        warnings.append("Resume used the legacy mixed-employer relevant-experience section")
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
        raise MaterialGenerationV5Error(f"Unsupported material type: {material_type}")

    rebuild_result = rebuild_user_evidence(db, user) if rebuild_evidence else None
    eligible = eligible_evidence_query(db, user.id).all()
    ranked = v4._curated_ranked(eligible, job)

    if material_type == "cover_letter":
        content, claims, warnings = _cover_letter_content(user, job, ranked)
    else:
        content, claims, warnings = _resume_summary_content(user, job, ranked)

    warnings.extend(base.validate_claims(claims, eligible))
    unit_by_id = {unit.id: unit for unit in eligible}
    warnings.extend(_v4_compatible_quality_warnings(content, claims, job, unit_by_id))
    warnings.extend(_v5_quality_warnings(content, material_type))

    substantive = [
        claim
        for claim in claims
        if claim.get("applicant_fact", True)
        and claim.get("category") != "identity"
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
            int(unit_id)
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
            "quality_policy": "role-aware-rendering-v4",
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
