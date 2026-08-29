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


GENERATOR_VERSION = "verified-material-v2"
SUPPORTED_MATERIAL_TYPES = {"cover_letter", "resume_summary"}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.#/-]{1,}", re.IGNORECASE)
LEADING_BULLET_RE = re.compile(r"^\s*(?:[•·▪◦\uf0b7]\s*|[-*–]\s+)")
MALFORMED_PUNCTUATION_RE = re.compile(r"[,;:]\s*\.")
TRAILING_FRAGMENT_RE = re.compile(
    r"(?:[,;:]|\b(?:and|or|when|while|because|including)|,\s*and\s+(?:internal|strong))\s*[.!?\"'”’]*\s*$",
    re.IGNORECASE,
)
TRAILING_LOWERCASE_ARTICLE_RE = re.compile(
    r"\b(?:the|a|an)\s*[.!?\"'”’]*\s*$"
)
GENERIC_ALIGNMENT_TERMS = {
    "data",
    "management",
    "time",
    "tools",
    "using",
}
SKILL_DISPLAY_ALIASES = {
    "ai tools": "AI Tools",
    "risk management": "Risk Management",
    "data analysis": "Data Analysis",
    "time managements": "Time Management",
    "microsoft office": "Microsoft Office",
    "linux": "Linux",
    "debian": "Debian",
    "descalation": "De-escalation",
    "bilingual": "Bilingual",
    "tsys": "TSYS",
    "ts2": "TS2",
}
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
NARRATIVE_KINDS = {"employment", "achievement", "project", "summary"}
FRAGMENT_SENSITIVE_KINDS = NARRATIVE_KINDS | {
    "skill",
    "credential",
    "education",
    "language",
    "role",
    "experience",
}
FRAGMENT_SENSITIVE_CATEGORIES = {
    "employment",
    "career_summary",
    "achievement",
    "project",
    "skill",
    "credential",
    "education",
    "language",
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


def _clean_material_statement(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    text = LEADING_BULLET_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text


def _display_skill(value: Any) -> str:
    text = _clean_material_statement(value)
    return SKILL_DISPLAY_ALIASES.get(text.casefold(), text)


def _narrative_fragment_reason(
    value: Any,
    *,
    reject_pdf_bullet: bool = True,
) -> str | None:
    raw = str(value or "")
    text = _clean_material_statement(raw)
    if not text:
        return "empty statement"
    if reject_pdf_bullet and "\uf0b7" in raw:
        return "private-use bullet glyph"
    if MALFORMED_PUNCTUATION_RE.search(text):
        return "malformed punctuation"
    if TRAILING_FRAGMENT_RE.search(text):
        return "truncated or dangling ending"
    if TRAILING_LOWERCASE_ARTICLE_RE.search(text):
        return "truncated or dangling ending"
    return None


def _usable_narrative_unit(unit: EvidenceUnit) -> bool:
    if unit.kind in FRAGMENT_SENSITIVE_KINDS:
        reason = _narrative_fragment_reason(
            unit.statement,
            reject_pdf_bullet=False,
        )
        if reason:
            return False
    if unit.kind == "employment" and unit.role:
        role_reason = _narrative_fragment_reason(
            unit.role,
            reject_pdf_bullet=False,
        )
        if role_reason:
            return False
    return True


def _clean_units(
    ranked: Iterable[EvidenceUnit],
    kinds: set[str],
    *,
    limit: int,
) -> list[EvidenceUnit]:
    return [
        unit
        for unit in ranked
        if unit.kind in kinds and _usable_narrative_unit(unit)
    ][:limit]


def _as_phrase(value: Any) -> str:
    text = _clean_material_statement(value).strip()
    if not text:
        return ""
    return re.sub(r"[.!?]+(?=(?:[\"'”’]*)$)", "", text).strip()


def _as_sentence(value: Any) -> str:
    text = _clean_material_statement(value).rstrip()
    if not text:
        return ""
    if not re.search(r"[.!?][\"'”’]*$", text):
        text += "."
    return text


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


def _alignment_terms(job: Job, units: Iterable[EvidenceUnit], *, limit: int = 6) -> list[str]:
    evidence_terms: set[str] = set()
    for unit in units:
        evidence_terms.update(_tokens(_clean_material_statement(unit.statement)))
    return sorted(
        term
        for term in (_job_terms(job) & evidence_terms)
        if term not in GENERIC_ALIGNMENT_TERMS
    )[:limit]


def _units_supporting_terms(
    units: Iterable[EvidenceUnit],
    terms: Iterable[str],
) -> list[EvidenceUnit]:
    emitted = {str(term).casefold() for term in terms}
    if not emitted:
        return []
    return [
        unit
        for unit in units
        if emitted & _tokens(_clean_material_statement(unit.statement))
    ]


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

    current_role = next(
        (
            unit
            for unit in ranked
            if unit.kind == "role" and _usable_narrative_unit(unit)
        ),
        None,
    )
    years = next(
        (
            unit
            for unit in ranked
            if unit.kind == "experience" and _usable_narrative_unit(unit)
        ),
        None,
    )
    if current_role and years:
        sentence = (
            f"My background includes {_as_phrase(years.statement)} years of "
            f"experience, including work as {_as_phrase(current_role.statement)}."
        )
        opening_parts.append(sentence)
        claims.append(_claim(sentence, [current_role, years], category="career_summary"))
    elif current_role:
        sentence = (
            "My background includes experience as "
            f"{_as_phrase(current_role.statement)}."
        )
        opening_parts.append(sentence)
        claims.append(_claim(sentence, [current_role], category="career_summary"))
    elif years:
        sentence = (
            f"My background includes {_as_phrase(years.statement)} years of experience."
        )
        opening_parts.append(sentence)
        claims.append(_claim(sentence, [years], category="career_summary"))
    else:
        warnings.append("No source-backed current role or years-of-experience statement was available")
    paragraphs.append(" ".join(opening_parts))

    employment_candidates = [unit for unit in ranked if unit.kind == "employment"]
    employment = _clean_units(ranked, {"employment"}, limit=3)
    employment_alignment_unit_ids: set[int] = set()
    if employment:
        role_items: list[tuple[str, EvidenceUnit]] = []
        detail_units: list[EvidenceUnit] = []
        for unit in employment:
            if unit.organization and unit.role:
                sentence = _as_sentence(
                    f"My experience includes work as {_as_phrase(unit.role)} "
                    f"with {_clean_material_statement(unit.organization)}"
                )
                if sentence not in {item[0] for item in role_items}:
                    role_items.append((sentence, unit))
            else:
                detail_units.append(unit)

        rendered_roles = role_items[:2]
        if rendered_roles:
            paragraphs.append(" ".join(sentence for sentence, _ in rendered_roles))
            for sentence, unit in rendered_roles:
                claims.append(_claim(sentence, [unit], category="employment"))

        if detail_units:
            terms = _alignment_terms(job, detail_units, limit=6)
            if terms:
                sentence = (
                    "My documented employment history also covers areas directly relevant to "
                    "this role, including " + ", ".join(terms) + "."
                )
                supporting_units = _units_supporting_terms(detail_units, terms)
                employment_alignment_unit_ids.update(unit.id for unit in supporting_units)
                paragraphs.append(sentence)
                claims.append(
                    _claim(
                        sentence,
                        supporting_units,
                        category="job_alignment",
                        applicant_fact=True,
                    )
                )
            elif not rendered_roles:
                sentence = " ".join(_as_sentence(unit.statement) for unit in detail_units)
                paragraphs.append(sentence)
                for unit in detail_units:
                    claims.append(
                        _claim(
                            _as_sentence(unit.statement),
                            [unit],
                            category="employment",
                        )
                    )
    elif employment_candidates:
        warnings.append("No complete source-backed employment statement was available")
    else:
        warnings.append("No source-backed employment history was available")

    relevant = [
        unit
        for unit in ranked
        if unit.kind in {"achievement", "skill", "credential", "project", "language"}
        and _usable_narrative_unit(unit)
    ][:8]
    if relevant:
        grouped: dict[str, list[EvidenceUnit]] = defaultdict(list)
        for unit in relevant:
            grouped[unit.kind].append(unit)

        detail_sentences: list[str] = []
        labels = {
            "achievement": "Selected documented achievements include",
            "skill": "My documented skills include",
            "credential": "My documented credentials include",
            "project": "My documented project experience includes",
            "language": "My documented language capabilities include",
        }
        for kind in ("achievement", "skill", "credential", "project", "language"):
            group = grouped.get(kind) or []
            if not group:
                continue
            values = "; ".join(
                _display_skill(unit.statement)
                if kind == "skill"
                else _clean_material_statement(unit.statement)
                for unit in group[:4]
            )
            sentence = f"{labels[kind]} {values}."
            detail_sentences.append(sentence)
            claims.append(_claim(sentence, group[:4], category=kind))
        if detail_sentences:
            paragraphs.append(" ".join(detail_sentences))
    else:
        warnings.append("No source-backed achievements, skills, credentials, projects, or languages were available")

    alignment_source = [
        unit
        for unit in [*employment, *relevant]
        if unit.id not in employment_alignment_unit_ids
    ]
    alignment_terms = _alignment_terms(job, alignment_source)
    if alignment_terms:
        sentence = (
            "Together, this background overlaps with the posting in areas including "
            + ", ".join(alignment_terms)
            + "."
        )
        paragraphs.append(sentence)
        claims.append(
            _claim(
                sentence,
                _units_supporting_terms(alignment_source, alignment_terms),
                category="job_alignment",
                applicant_fact=True,
            )
        )

    paragraphs.append(
        "Thank you for considering my application. I would welcome the opportunity to discuss how my experience could support your team and customers."
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
        unit
        for unit in ranked
        if unit.kind in {"role", "experience", "summary"}
        and (unit.kind not in FRAGMENT_SENSITIVE_KINDS or _usable_narrative_unit(unit))
    ][:3]
    employment = _clean_units(ranked, {"employment"}, limit=5)
    if summary_units:
        current_role = next((unit for unit in summary_units if unit.kind == "role"), None)
        years = next((unit for unit in summary_units if unit.kind == "experience"), None)
        narrative = next((unit for unit in summary_units if unit.kind == "summary"), None)
        summary_parts: list[str] = []
        summary_claim_units: list[EvidenceUnit] = []
        if current_role and years:
            summary_parts.append(
                f"{_as_phrase(current_role.statement)} with "
                f"{_as_phrase(years.statement)} years of experience."
            )
            summary_claim_units.extend([current_role, years])
        elif current_role:
            summary_parts.append(
                f"Background includes experience as {_as_phrase(current_role.statement)}."
            )
            summary_claim_units.append(current_role)
        elif years:
            summary_parts.append(
                f"Background includes {_as_phrase(years.statement)} years of experience."
            )
            summary_claim_units.append(years)
        if narrative:
            summary_parts.append(_as_sentence(narrative.statement))
            summary_claim_units.append(narrative)
        terms = _alignment_terms(job, employment, limit=5)
        summary_employment_units: list[EvidenceUnit] = []
        if terms:
            summary_parts.append(
                "Documented experience overlaps with this role in " + ", ".join(terms) + "."
            )
            summary_employment_units = _units_supporting_terms(employment, terms)
        summary = " ".join(part for part in summary_parts if part)
        sections.append(f"PROFESSIONAL SUMMARY\n{summary}")
        claims.append(
            _claim(
                summary,
                [*summary_claim_units, *summary_employment_units],
                category="career_summary",
            )
        )
    else:
        warnings.append("No source-backed professional summary evidence was available")

    employment_candidates = [unit for unit in ranked if unit.kind == "employment"]
    if employment:
        lines = [f"• {_clean_material_statement(unit.statement)}" for unit in employment]
        sections.append("RELEVANT EXPERIENCE\n" + "\n".join(lines))
        for unit in employment:
            claims.append(
                _claim(
                    _clean_material_statement(unit.statement),
                    [unit],
                    category="employment",
                )
            )
    elif employment_candidates:
        warnings.append("No complete source-backed employment statement was available")
    else:
        warnings.append("No source-backed employment evidence was available")

    skills = [
        unit
        for unit in ranked
        if unit.kind == "skill" and _usable_narrative_unit(unit)
    ][:12]
    if skills:
        line = ", ".join(_display_skill(unit.statement) for unit in skills)
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
        units = [
            unit
            for unit in ranked
            if unit.kind in kinds and _usable_narrative_unit(unit)
        ][:5]
        if not units:
            continue
        sections.append(
            heading
            + "\n"
            + "\n".join(f"• {_clean_material_statement(unit.statement)}" for unit in units)
        )
        for unit in units:
            claims.append(
                _claim(
                    _clean_material_statement(unit.statement),
                    [unit],
                    category=category,
                )
            )

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

        text = str(claim.get("text") or "")
        if "\uf0b7" in text:
            warnings.append(f"Claim {index} contains an unsafe PDF bullet glyph")
        if MALFORMED_PUNCTUATION_RE.search(text):
            warnings.append(f"Claim {index} contains malformed punctuation")
        if claim.get("category") in FRAGMENT_SENSITIVE_CATEGORIES:
            claim_items = [
                item.strip()
                for item in re.split(r"[;\n]+", text)
                if item.strip()
            ]
            for item_index, item in enumerate(claim_items):
                reason = _narrative_fragment_reason(item)
                if reason:
                    warnings.append(
                        f"Claim {index} item {item_index} contains a likely incomplete narrative: {reason}"
                    )

        for unit_id in ids:
            unit = unit_by_id[unit_id]
            if unit.kind in FRAGMENT_SENSITIVE_KINDS:
                reason = _narrative_fragment_reason(
                    unit.statement,
                    reject_pdf_bullet=False,
                )
                if reason:
                    warnings.append(
                        f"Claim {index} references likely incomplete {unit.kind} evidence unit {unit_id}: {reason}"
                    )
            if unit.kind == "employment" and unit.role:
                role_reason = _narrative_fragment_reason(
                    unit.role,
                    reject_pdf_bullet=False,
                )
                if role_reason:
                    warnings.append(
                        f"Claim {index} references likely incomplete employment role in evidence unit {unit_id}: {role_reason}"
                    )
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