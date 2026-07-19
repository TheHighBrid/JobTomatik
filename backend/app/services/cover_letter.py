"""Cover letter generator with a free local fallback."""

from typing import Any, Dict

try:
    import anthropic
except Exception:  # optional dependency/runtime
    anthropic = None

from app.config import get_settings


DEFAULT_BANKING_EMPLOYERS = [
    "TD Bank",
    "RBC",
    "BMO",
    "Scotiabank",
    "Tangerine",
]


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
        return ", ".join(str(v).strip() for v in list(values)[:limit] if str(v).strip())
    except Exception:
        return str(values)


def _employment_history(user_profile: Dict) -> str:
    raw = (
        _get(user_profile, "employment_history", "")
        or _get(user_profile, "experience_history", "")
        or _get(user_profile, "employers", "")
    )
    if isinstance(raw, list):
        entries = []
        for item in raw:
            if isinstance(item, dict):
                employer = str(item.get("employer") or item.get("company") or "").strip()
                role = str(item.get("role") or item.get("title") or "").strip()
                highlights = str(item.get("highlights") or item.get("experience") or "").strip()
                summary = " | ".join(part for part in (employer, role, highlights) if part)
                if summary:
                    entries.append(summary)
            elif str(item).strip():
                entries.append(str(item).strip())
        if entries:
            return "; ".join(entries)
    elif str(raw or "").strip():
        return str(raw).strip()
    return ", ".join(DEFAULT_BANKING_EMPLOYERS)


def _employer_names(history: str) -> str:
    names = []
    for entry in history.replace("\n", ";").split(";"):
        name = entry.split("|")[0].strip()
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f", and {names[-1]}" if names else "previous employers"


def _fallback_cover_letter(job: Dict, user_profile: Dict) -> str:
    title = _get(job, "title", "the position")
    company = _get(job, "company", "your organization")
    name = _get(user_profile, "full_name", "") or _get(user_profile, "name", "") or "Mohamed Alem"
    current_role = (
        _get(user_profile, "current_role", "")
        or _get(user_profile, "role", "")
        or "banking and customer service professional"
    )
    years_exp = _get(user_profile, "years_experience", "") or _get(user_profile, "experience_years", "") or "several"
    skills = _clean_list(
        _get(user_profile, "skills", "")
        or ["banking", "customer service", "bilingual English/French", "KYC", "AML", "fraud awareness", "risk review"]
    )
    achievements = _get(user_profile, "key_achievements", "") or _get(user_profile, "achievements", "")
    achievement_sentence = f" My background also includes {achievements}" if achievements else ""
    employment_history = _employment_history(user_profile)
    employer_names = _employer_names(employment_history)

    return f"""Dear Hiring Manager,

I am writing to express my interest in the {title} position at {company}. With {years_exp} years of experience as a {current_role}, I bring a strong foundation in {skills}, along with the judgment, accuracy, and professionalism required for high-trust banking and financial-crime work.

Across my roles with {employer_names}, I developed a careful and detail-oriented approach to reviewing client information, identifying potential issues, documenting actions clearly, and supporting customers through sensitive financial situations.{achievement_sentence} I understand the importance of confidentiality, regulatory awareness, and calm communication when dealing with financial risk.

What makes this opportunity especially appealing is the chance to contribute to {company} in a role where investigation, customer protection, compliance, and sound decision-making all matter. I am confident that my banking experience, bilingual English/French communication skills, and fraud/risk awareness would allow me to contribute quickly and responsibly.

Thank you for considering my application. I would welcome the opportunity to discuss how my background aligns with the needs of your team.

Best regards,
{name}
"""


async def generate_cover_letter(job: Dict, user_profile: Dict) -> str:
    settings = get_settings()
    ai_provider = (getattr(settings, "ai_provider", "template") or "template").lower().strip()

    if ai_provider in ("", "template", "free", "local", "none"):
        return _fallback_cover_letter(job, user_profile)

    if ai_provider == "anthropic":
        if not getattr(settings, "anthropic_api_key", "") or anthropic is None:
            return _fallback_cover_letter(job, user_profile)

        title = _get(job, "title", "the position")
        company = _get(job, "company", "your organization")
        description = str(_get(job, "description", ""))[:1500]
        requirements = str(_get(job, "requirements", ""))[:900]
        job_skills = _clean_list(_get(job, "skills", ""))
        name = _get(user_profile, "full_name", "") or "Mohamed Alem"
        current_role = _get(user_profile, "current_role", "") or "banking and customer service professional"
        years_exp = _get(user_profile, "years_experience", "") or "several"
        profile_skills = _clean_list(_get(user_profile, "skills", "")) or job_skills
        achievements = _get(user_profile, "key_achievements", "") or _get(user_profile, "achievements", "")
        employment_history = _employment_history(user_profile)

        prompt = f"""Write a professional Canadian banking cover letter.

Job:
Title: {title}
Company: {company}
Description: {description}
Requirements: {requirements}
Job skills: {job_skills}

Applicant:
Name: {name}
Current role: {current_role}
Years experience: {years_exp}
Skills: {profile_skills}
Achievements: {achievements}
Employment history: {employment_history}

Rules:
- Banking, fraud, AML, KYC, compliance, risk, and client-service tone only.
- Do not mention software engineering.
- Do not mention scalable systems.
- Do not mention coding.
- Do not mention engineering culture.
- Attribute experience to the employer or employers listed in the employment history.
- Do not invent an employer, role, responsibility, or achievement.
- Keep it under 350 words.
- Output only the letter text.
"""
        try:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            message = client.messages.create(
                model=getattr(settings, "anthropic_model", "claude-sonnet-5"),
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception:
            return _fallback_cover_letter(job, user_profile)

    return _fallback_cover_letter(job, user_profile)
