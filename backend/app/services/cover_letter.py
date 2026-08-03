"""Evidence-conservative cover letter fallback.

The source-mapped material pipeline lives in ``material_generation.py``. This module
remains as a compatibility path for older callers, but it never supplies default
employers, names, years, skills, roles, or achievements when the user did not provide
them.
"""

from typing import Any, Dict


def _get(obj: Any, key: str, default: Any = "") -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _clean_list(values: Any, limit: int = 8) -> str:
    if not values:
        return ""
    if isinstance(values, str):
        return values.strip()
    try:
        return ", ".join(
            str(value).strip()
            for value in list(values)[:limit]
            if str(value).strip()
        )
    except Exception:
        return str(values).strip()


def _employment_entries(user_profile: Dict) -> list[dict[str, str]]:
    raw = (
        _get(user_profile, "employment_history", "")
        or _get(user_profile, "experience_history", "")
        or _get(user_profile, "employers", "")
    )
    entries: list[dict[str, str]] = []
    if isinstance(raw, list):
        source_items = raw
    else:
        source_items = str(raw or "").replace("\r", "\n").replace(";", "\n").splitlines()

    for item in source_items:
        if isinstance(item, dict):
            employer = str(item.get("employer") or item.get("company") or "").strip()
            role = str(item.get("role") or item.get("title") or "").strip()
            detail = str(item.get("highlights") or item.get("experience") or "").strip()
        else:
            parts = [part.strip() for part in str(item or "").split("|")]
            employer = parts[0] if parts else ""
            role = parts[1] if len(parts) > 1 else ""
            detail = " | ".join(parts[2:]) if len(parts) > 2 else ""
        if employer or role or detail:
            entries.append({"employer": employer, "role": role, "detail": detail})
    return entries


def _fallback_cover_letter(job: Dict, user_profile: Dict) -> str:
    title = str(_get(job, "title", "the position") or "the position").strip()
    company = str(_get(job, "company", "your organization") or "your organization").strip()
    name = str(_get(user_profile, "full_name", "") or _get(user_profile, "name", "")).strip()
    current_role = str(
        _get(user_profile, "current_role", "")
        or _get(user_profile, "role", "")
    ).strip()
    years_exp = str(
        _get(user_profile, "years_experience", "")
        or _get(user_profile, "experience_years", "")
    ).strip()
    skills = _clean_list(_get(user_profile, "skills", ""))
    achievements = str(
        _get(user_profile, "key_achievements", "")
        or _get(user_profile, "achievements", "")
    ).strip()
    employment = _employment_entries(user_profile)

    paragraphs = [
        "Dear Hiring Manager,",
        f"I am writing to apply for the {title} position at {company}.",
    ]

    summary_parts = []
    if current_role:
        summary_parts.append(f"My profile identifies my current or most recent role as {current_role}")
    if years_exp:
        summary_parts.append(f"my profile records {years_exp} years of experience")
    if skills:
        summary_parts.append(f"my documented skills include {skills}")
    if summary_parts:
        paragraphs.append("; ".join(summary_parts) + ".")

    employment_sentences = []
    for entry in employment[:5]:
        employer = entry["employer"]
        role = entry["role"]
        detail = entry["detail"]
        if employer and role:
            sentence = f"My employment history includes {role} experience with {employer}"
        elif employer:
            sentence = f"My employment history includes experience with {employer}"
        elif role:
            sentence = f"My employment history includes experience as {role}"
        else:
            sentence = "My employment history includes the following documented detail"
        if detail:
            sentence += f": {detail}"
        employment_sentences.append(sentence + ".")
    if employment_sentences:
        paragraphs.append(" ".join(employment_sentences))

    if achievements:
        paragraphs.append(f"My documented achievements include {achievements}.")

    paragraphs.append(
        "Thank you for considering my application. I would welcome the opportunity "
        "to discuss the documented experience above in relation to your team’s needs."
    )
    paragraphs.append(f"Best regards,\n{name}" if name else "Best regards")
    return "\n\n".join(paragraphs).strip() + "\n"


async def generate_cover_letter(job: Dict, user_profile: Dict) -> str:
    """Return the deterministic compatibility letter without inventing profile facts."""
    return _fallback_cover_letter(job, user_profile)
