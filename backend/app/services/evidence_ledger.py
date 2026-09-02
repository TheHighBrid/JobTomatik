from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.intelligence import CareerMemory
from app.models.material import EvidenceUnit
from app.models.user import User

try:
    from pypdf import PdfReader
except Exception:  # Optional until dependency installation completes.
    PdfReader = None


LEDGER_VERSION = "evidence-ledger-v1"
ACTIVE_STATUSES = {"source_backed", "user_confirmed", "verified"}
MANAGED_SOURCE_TYPES = {"profile", "resume_pdf", "career_memory"}
SECTION_KIND = {
    "experience": "employment",
    "employment": "employment",
    "work experience": "employment",
    "professional experience": "employment",
    "achievements": "achievement",
    "accomplishments": "achievement",
    "education": "education",
    "skills": "skill",
    "technical skills": "skill",
    "core skills": "skill",
    "certifications": "credential",
    "certificates": "credential",
    "languages": "language",
    "projects": "project",
    "summary": "summary",
    "profile": "summary",
}


def normalize_statement(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:[•·▪◦]\s*|[-–—]\s+)", "", text)
    text = text.rstrip(" \t\r\n•·▪◦-–—")
    return text[:5000]


def evidence_hash(
    statement: str,
    *,
    kind: str = "",
    organization: str = "",
    role: str = "",
) -> str:
    payload = "|".join(
        [
            normalize_statement(kind).casefold(),
            normalize_statement(organization).casefold(),
            normalize_statement(role).casefold(),
            normalize_statement(statement).casefold(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = " | ".join(
                    normalize_statement(item.get(key))
                    for key in ("employer", "company", "role", "title", "highlights", "experience")
                    if normalize_statement(item.get(key))
                )
                if text:
                    result.append(text)
            else:
                text = normalize_statement(item)
                if text:
                    result.append(text)
        return result
    text = str(value or "").replace("\r", "\n")
    parts = re.split(r"\n+|\s*;\s*", text)
    return [normalize_statement(part) for part in parts if normalize_statement(part)]


def _candidate(
    *,
    kind: str,
    label: str,
    statement: str,
    source_type: str,
    source_ref: str,
    verification_status: str = "source_backed",
    confidence: float = 0.85,
    organization: str | None = None,
    role: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized = normalize_statement(statement)
    if len(normalized) < 2:
        return None
    return {
        "kind": normalize_statement(kind).lower() or "other",
        "label": normalize_statement(label)[:255] or "Evidence",
        "statement": normalized,
        "organization": normalize_statement(organization)[:255] or None,
        "role": normalize_statement(role)[:255] or None,
        "source_type": source_type,
        "source_ref": source_ref[:1000],
        "source_hash": evidence_hash(
            normalized,
            kind=kind,
            organization=organization or "",
            role=role or "",
        ),
        "verification_status": verification_status,
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "provenance": {"ledger_version": LEDGER_VERSION, **(provenance or {})},
    }


def profile_evidence_candidates(user: User) -> list[dict[str, Any]]:
    profile = dict(user.profile_data or {})
    preferences = dict(user.job_preferences or {})
    candidates: list[dict[str, Any]] = []

    direct_fields = [
        ("identity", "Full name", user.full_name, "profile:full_name"),
        ("identity", "Email", user.email, "profile:email"),
        ("identity", "Phone", user.phone, "profile:phone"),
        ("location", "Address", user.address, "profile:address"),
        ("role", "Current role", profile.get("current_role"), "profile:current_role"),
        ("experience", "Years of experience", profile.get("years_experience"), "profile:years_experience"),
    ]
    for kind, label, value, source_ref in direct_fields:
        item = _candidate(
            kind=kind,
            label=label,
            statement=value,
            source_type="profile",
            source_ref=source_ref,
            verification_status="user_confirmed",
            confidence=1.0,
            provenance={"field": source_ref.split(":", 1)[1]},
        )
        if item:
            candidates.append(item)

    for index, skill in enumerate(_split_values(preferences.get("skills"))):
        item = _candidate(
            kind="skill",
            label=skill,
            statement=skill,
            source_type="profile",
            source_ref=f"profile:skills:{index}",
            verification_status="user_confirmed",
            confidence=0.95,
            provenance={"field": "job_preferences.skills", "index": index},
        )
        if item:
            candidates.append(item)

    for index, entry in enumerate(_split_values(profile.get("employment_history"))):
        parts = [normalize_statement(part) for part in entry.split("|")]
        organization = parts[0] if parts else None
        role = parts[1] if len(parts) > 1 else None
        detail = parts[2] if len(parts) > 2 else entry
        statement = entry if len(parts) <= 2 else f"{organization} | {role} | {detail}"
        item = _candidate(
            kind="employment",
            label="Employment history",
            statement=statement,
            organization=organization,
            role=role,
            source_type="profile",
            source_ref=f"profile:employment_history:{index}",
            verification_status="user_confirmed",
            confidence=1.0,
            provenance={"field": "profile_data.employment_history", "index": index},
        )
        if item:
            candidates.append(item)

    repeated_fields = {
        "key_achievements": ("achievement", "Achievement"),
        "education": ("education", "Education"),
        "certifications": ("credential", "Certification"),
        "languages": ("language", "Language"),
        "projects": ("project", "Project"),
    }
    for field, (kind, label) in repeated_fields.items():
        for index, value in enumerate(_split_values(profile.get(field))):
            item = _candidate(
                kind=kind,
                label=label,
                statement=value,
                source_type="profile",
                source_ref=f"profile:{field}:{index}",
                verification_status="user_confirmed",
                confidence=1.0,
                provenance={"field": f"profile_data.{field}", "index": index},
            )
            if item:
                candidates.append(item)

    return candidates


def career_memory_candidates(memories: Iterable[CareerMemory]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for memory in memories:
        if not memory.is_active or not normalize_statement(memory.content):
            continue
        source = str(memory.source or "memory")
        status = "user_confirmed" if source in {"user", "manual"} else "source_backed"
        item = _candidate(
            kind=memory.kind or "memory",
            label=memory.key or "Career memory",
            statement=memory.content,
            source_type="career_memory",
            source_ref=f"career_memory:{memory.id}",
            verification_status=status,
            confidence=memory.confidence,
            provenance={
                "career_memory_id": memory.id,
                "memory_source": source,
                "memory_source_ref": memory.source_ref,
            },
        )
        if item:
            candidates.append(item)
    return candidates


def extract_pdf_text(path: str | Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if PdfReader is None:
        return "", ["pypdf is unavailable; résumé text extraction was skipped"]
    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for page_number, page in enumerate(reader.pages):
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:
                warnings.append(f"Page {page_number + 1} text extraction failed: {type(exc).__name__}")
        return "\n".join(pages), warnings
    except Exception as exc:
        return "", [f"Résumé text extraction failed: {type(exc).__name__}"]


def resume_text_candidates(
    text: str,
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    section = "resume"
    seen: set[str] = set()
    for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = normalize_statement(raw_line)
        if not line:
            continue
        lowered = line.casefold().rstrip(":")
        if lowered in SECTION_KIND:
            section = lowered
            continue
        if len(line) < 3 or line.casefold() in seen:
            continue
        seen.add(line.casefold())
        kind = SECTION_KIND.get(section, "resume_fact")
        item = _candidate(
            kind=kind,
            label=section.title() if section != "resume" else "Résumé statement",
            statement=line,
            source_type="resume_pdf",
            source_ref=f"{source_ref}:line:{line_number}",
            verification_status="source_backed",
            confidence=0.85,
            provenance={
                "document": source_ref,
                "line_number": line_number,
                "section": section,
                "verbatim": True,
            },
        )
        if item:
            candidates.append(item)
        if len(candidates) >= 250:
            break
    return candidates


def _upsert_candidate(db: Session, user_id: int, data: dict[str, Any]) -> tuple[EvidenceUnit, bool]:
    existing = (
        db.query(EvidenceUnit)
        .filter(
            EvidenceUnit.user_id == user_id,
            EvidenceUnit.source_type == data["source_type"],
            EvidenceUnit.source_ref == data["source_ref"],
            EvidenceUnit.source_hash == data["source_hash"],
        )
        .first()
    )
    if existing:
        existing.is_active = True
        existing.label = data["label"]
        existing.statement = data["statement"]
        existing.organization = data["organization"]
        existing.role = data["role"]
        existing.verification_status = data["verification_status"]
        existing.confidence = data["confidence"]
        existing.provenance = data["provenance"]
        return existing, False

    unit = EvidenceUnit(user_id=user_id, is_active=True, **data)
    db.add(unit)
    db.flush()
    return unit, True


def rebuild_user_evidence(db: Session, user: User) -> dict[str, Any]:
    candidates = profile_evidence_candidates(user)
    memories = (
        db.query(CareerMemory)
        .filter(CareerMemory.user_id == user.id, CareerMemory.is_active.is_(True))
        .all()
    )
    candidates.extend(career_memory_candidates(memories))

    warnings: list[str] = []
    if user.resume_path and Path(user.resume_path).exists():
        text, pdf_warnings = extract_pdf_text(user.resume_path)
        warnings.extend(pdf_warnings)
        source_ref = f"resume:{user.resume_filename or Path(user.resume_path).name}"
        candidates.extend(resume_text_candidates(text, source_ref=source_ref))

    managed_existing = (
        db.query(EvidenceUnit)
        .filter(
            EvidenceUnit.user_id == user.id,
            EvidenceUnit.source_type.in_(sorted(MANAGED_SOURCE_TYPES)),
            EvidenceUnit.is_active.is_(True),
        )
        .all()
    )
    active_keys = {
        (item["source_type"], item["source_ref"], item["source_hash"])
        for item in candidates
    }
    deactivated = 0
    for unit in managed_existing:
        key = (unit.source_type, unit.source_ref, unit.source_hash)
        if key not in active_keys:
            unit.is_active = False
            deactivated += 1

    created = 0
    reused = 0
    sources: Counter[str] = Counter()
    for data in candidates:
        _, is_created = _upsert_candidate(db, user.id, data)
        created += int(is_created)
        reused += int(not is_created)
        sources[data["source_type"]] += 1

    db.flush()
    total_active = (
        db.query(EvidenceUnit)
        .filter(EvidenceUnit.user_id == user.id, EvidenceUnit.is_active.is_(True))
        .count()
    )
    return {
        "created": created,
        "reused": reused,
        "deactivated": deactivated,
        "total_active": total_active,
        "sources": dict(sources),
        "warnings": warnings,
    }


def create_manual_evidence(
    db: Session,
    user: User,
    *,
    kind: str,
    label: str,
    statement: str,
    organization: str | None = None,
    role: str | None = None,
    source_ref: str | None = None,
    confidence: float = 1.0,
    provenance: dict[str, Any] | None = None,
) -> EvidenceUnit:
    now_ref = source_ref or f"manual:{datetime.now(timezone.utc).isoformat()}"
    data = _candidate(
        kind=kind,
        label=label,
        statement=statement,
        organization=organization,
        role=role,
        source_type="manual",
        source_ref=now_ref,
        verification_status="user_confirmed",
        confidence=confidence,
        provenance={"created_by_user": True, **(provenance or {})},
    )
    if not data:
        raise ValueError("Evidence statement is empty")
    unit, _ = _upsert_candidate(db, user.id, data)
    return unit


def eligible_evidence_query(db: Session, user_id: int):
    return db.query(EvidenceUnit).filter(
        EvidenceUnit.user_id == user_id,
        EvidenceUnit.is_active.is_(True),
        EvidenceUnit.verification_status.in_(sorted(ACTIVE_STATUSES)),
    )
