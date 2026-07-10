"""Cover letter generator with a free local fallback."""

from typing import Any, Dict

try:
    import anthropic
except Exception:  # optional dependency/runtime
    anthropic = None

from app.config import get_settings


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

    return f"""Dear Hiring Manager,

I am writing to express my interest in the {title} position at {company}. With {years_exp} years of experience as a {current_role}, I bring a strong foundation in {skills}, along with the judgment, accuracy, and professionalism required for high-trust banking and financial-crime work.

In my previous roles, I developed a careful and detail-oriented approach to reviewing client information, identifying potential issues, documenting actions clearly, and supporting customers through sensitive financial situations.{achievement_sentence} I understand the importance of confidentiality, regulatory awareness, and calm communication when dealing with financial risk.

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

Rules:
- Banking, fraud, AML, KYC, compliance, risk, and client-service tone only.
- Do not mention software engineering.
- Do not mention scalable systems.
- Do not mention coding.
- Do not mention engineering culture.
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
