from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.material import ApplicationMaterial, ApplicationMaterialEvidence, EvidenceUnit
from app.models.user import User
from app.services import material_generation as base
from app.services import material_generation_v4 as v4
from app.services import material_generation_v5 as v5
from app.services.evidence_ledger import eligible_evidence_query, rebuild_user_evidence


V5_STRUCTURAL_HEADINGS = (
    "EMPLOYMENT HISTORY",
    "RELEVANT SUPPORT EXPERIENCE",
)

CLIENT_SUCCESS_SKILL_ORDER = {
    "bilingual": 160,
    "reporting": 145,
    "data analysis": 130,
    "de-escalation": 120,
    "time management": 115,
    "microsoft office": 100,
}

CLIENT_SUCCESS_SPECIALIST_EXCLUSIONS = {
    "ai tools",
    "debian",
    "ip tracking",
    "linux",
    "tsys",
}

_CLIENT_SUCCESS_SIGNALS = (
    "client success",
    "account management",
    "client-facing",
    "portfolio",
    "channel partner",
    "channel partners",
    "renewal",
    "renewals",
    "salesforce",
    "crm",
)

_TECHNICAL_SUPPORT_SIGNALS = (
    "technical support",
    "technical issue",
    "technical issues",
    "troubleshoot",
    "troubleshooting",
    "api",
    "apis",
    "web technologies",
    "reproduction steps",
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


def _job_text(job: Job) -> str:
    return " ".join(
        str(value or "").strip().casefold()
        for value in (
            job.title,
            job.description,
            job.requirements,
            " ".join(job.skills or []),
        )
        if value
    )


def _contains_signal(text: str, signal: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(signal)}(?!\w)", text) is not None


def _is_client_success_job(job: Job) -> bool:
    text = _job_text(job)
    return any(_contains_signal(text, signal) for signal in _CLIENT_SUCCESS_SIGNALS)


def _is_technical_support_job(job: Job) -> bool:
    text = _job_text(job)
    return any(_contains_signal(text, signal) for signal in _TECHNICAL_SUPPORT_SIGNALS)


def _role_aware_ranked(
    ranked: list[EvidenceUnit],
    job: Job,
) -> list[EvidenceUnit]:
    """Keep v5's technical-support behavior, but curate client-success skills separately."""

    if not _is_client_success_job(job) or _is_technical_support_job(job):
        return ranked

    non_skills = [unit for unit in ranked if unit.kind != "skill"]
    skill_rows: list[tuple[int, int, EvidenceUnit]] = []

    for index, unit in enumerate(ranked):
        if unit.kind != "skill" or not base._usable_narrative_unit(unit):
            continue

        display = base._display_skill(unit.statement).casefold()
        if display in CLIENT_SUCCESS_SPECIALIST_EXCLUSIONS:
            continue

        priority = CLIENT_SUCCESS_SKILL_ORDER.get(display)
        overlap = v4._job_overlap_count(unit, job)

        if priority is None:
            # A single shared token such as "tracking" is too weak to elevate a
            # specialist skill into a client-success package.
            if overlap < 2:
                continue
            priority = 80 + overlap * 20
        else:
            priority += overlap * 20

        skill_rows.append((-priority, index, unit))

    skill_rows.sort(key=lambda item: (item[0], item[1]))
    return non_skills + [unit for _, _, unit in skill_rows]


def _client_success_alignment_sentence(job: Job) -> str:
    text = _job_text(job)
    items: list[str] = []

    if "bilingual" in text or ("french" in text and "english" in text):
        items.append("bilingual partner communication")
    if any(term in text for term in ("portfolio", "channel partner", "client success")):
        items.append("partner relationship management")
    if "renewal" in text:
        items.append("renewal coordination")
    if "reporting" in text or "data" in text:
        items.append("reporting and portfolio insights")
    if "cross-functional" in text or "collaborat" in text:
        items.append("cross-functional collaboration")

    items = items[:3]
    if not items:
        return v5._target_alignment_sentence(job)

    if len(items) == 1:
        focus = items[0]
    elif len(items) == 2:
        focus = f"{items[0]} and {items[1]}"
    else:
        focus = f"{items[0]}, {items[1]}, and {items[2]}"

    return (
        f"I am particularly interested in {job.company}'s {job.title} role and its "
        f"focus on {focus}."
    )


def _rewrite_client_success_material(
    content: str,
    claims: list[dict[str, Any]],
    job: Job,
) -> tuple[str, list[dict[str, Any]]]:
    if not _is_client_success_job(job) or _is_technical_support_job(job):
        return content, claims

    old_alignment = v5._target_alignment_sentence(job)
    new_alignment = _client_success_alignment_sentence(job)

    def rewrite_text(value: str) -> str:
        text = str(value or "")
        text = text.replace(
            " and documented technical skills in ",
            " and documented strengths in ",
        )
        text = text.replace(
            " and technical skills in ",
            " and documented strengths in ",
        )
        if old_alignment in text:
            text = text.replace(old_alignment, new_alignment)
        return text

    rewritten_claims = []
    for claim in claims:
        updated = dict(claim)
        if updated.get("category") == "target_alignment":
            updated["text"] = new_alignment
        else:
            updated["text"] = rewrite_text(updated.get("text", ""))
        rewritten_claims.append(updated)

    return rewrite_text(content), rewritten_claims


def generate_application_material(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    material_type: str = "cover_letter",
    rebuild_evidence: bool = True,
) -> ApplicationMaterial:
    if material_type not in v5.SUPPORTED_MATERIAL_TYPES:
        raise v5.MaterialGenerationV5Error(
            f"Unsupported material type: {material_type}"
        )

    rebuild_result = rebuild_user_evidence(db, user) if rebuild_evidence else None
    eligible = eligible_evidence_query(db, user.id).all()
    ranked = v4._curated_ranked(eligible, job)
    ranked = _role_aware_ranked(ranked, job)

    if material_type == "cover_letter":
        content, claims, warnings = v5._cover_letter_content(user, job, ranked)
    else:
        content, claims, warnings = v5._resume_summary_content(user, job, ranked)

    content, claims = _rewrite_client_success_material(content, claims, job)

    warnings.extend(base.validate_claims(claims, eligible))
    unit_by_id = {unit.id: unit for unit in eligible}
    warnings.extend(v5._v4_compatible_quality_warnings(content, claims, job, unit_by_id))
    warnings.extend(v5._v5_quality_warnings(content, material_type))

    substantive = [
        claim
        for claim in claims
        if claim.get("applicant_fact", True)
        and claim.get("category") != "identity"
        and claim.get("evidence_unit_ids")
    ]
    if not substantive:
        warnings.append(
            "No substantive applicant claim could be supported by active evidence"
        )

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
            "quality_policy": "role-aware-rendering-v5-client-success-policy",
        },
        generator_version=v5.GENERATOR_VERSION,
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
    _normalize_v5_structural_warnings(material)
    db.flush()
    return material
