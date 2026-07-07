"""
Cover letter generator.

The default provider is a free local template. Paid AI providers are optional
and must never be required for the app to work.
"""

from typing import Dict, Iterable, Optional, Union

try:
    import anthropic
except Exception:  # pragma: no cover - optional dependency/runtime
    anthropic = None

from app.config import get_settings

settings = get_settings()


def _clean_list(values: Optional[Union[Iterable[str], str]], limit: int = 8) -> str:
    if not values:
        return ""
    if isinstance(values, str):
        return values.strip()
    return ", ".join(str(v).strip() for v in list(values)[:limit] if str(v).strip())


def _fallback_cover_letter(job: Dict, user_profile: Dict) -> str:
    title = job.get("title") or "the position"
    company = job.get("company") or "your organization"

    profile_skills = user_profile.get("skills") or []
    job_skills = job.get("skills") or []
    skills = (
        _clean_list(profile_skills, 7)
        or _clean_list(job_skills, 7)
        or "banking, fraud prevention, AML, KYC, compliance, client service, and risk analysis"
    )

    name = user_profile.get("full_name") or "Applicant"
    current_role = user_profile.get("current_role") or "banking professional"
    years_exp = user_profile.get("years_experience") or "several"
    achievements = (user_profile.get("key_achievements") or "").strip()

    achievement_sentence = (
        "My background includes measurable compliance-focused work, including KYC accuracy, "
        "audit-ready documentation, quality assurance, fraud awareness, and client issue resolution."
        if achievements
        else "My background includes careful documentation, sensitive client support, policy awareness, and risk-focused decision-making."
    )

    return f"""Dear Hiring Team,

I am writing to express my interest in the {title} position at {company}. With {years_exp} years of experience as a {current_role}, I bring a strong foundation in {skills}, along with the judgment, accuracy, and professionalism required for high-trust banking and financial-crime work.

In my previous roles, I developed a careful and detail-oriented approach to reviewing client information, identifying potential issues, documenting actions clearly, and supporting customers through sensitive financial situations. {achievement_sentence} I understand the importance of confidentiality, regulatory awareness, and calm communication when dealing with financial risk.

What makes this opportunity especially appealing is the chance to contribute to {company} in a role where investigation, customer protection, compliance, and sound decision-making all matter. I am confident that my banking experience, bilingual communication skills, and fraud/risk awareness would allow me to contribute quickly and responsibly.

Thank you for considering my application. I would welcome the opportunity to discuss how my background aligns with the needs of your team.

Best regards,
{name}
"""


async def generate_cover_letter(job: Dict, user_profile: Dict) -> str:
    ai_provider = (getattr(settings, "ai_provider", "template") or "template").lower().strip()

    if ai_provider in ("", "template", "free", "local", "none"):
        return _fallback_cover_letter(job, user_profile)

    if ai_provider == "anthropic":
        if not getattr(settings, "anthropic_api_key", "") or anthropic is None:
            return _fallback_cover_letter(job, user_profile)

        title = job.get("title") or "the position"
        company = job.get("company") or "your organization"
        description = job.get("description") or ""
        requirements = job.get("requirements") or ""
        skills = _clean_list(job.get("skills") or [], 8) or "banking and compliance"
        name = user_profile.get("full_name") or "Applicant"
        current_role = user_profile.get("current_role") or "banking professional"
        years_exp = user_profile.get("years_experience") or "several"
        profile_skills = _clean_list(user_profile.get("skills") or [], 8) or skills
        achievements = user_profile.get("key_achievements") or ""
        linkedin = user_profile.get("linkedin_url") or ""

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = f"""Write a professional Canadian banking cover letter.

Job:
- Title: {title}
- Company: {company}
- Description: {description[:1500]}
- Requirements: {requirements[:900]}
- Job skills: {skills}

Applicant:
- Name: {name}
- Current/most recent role: {current_role}
- Years of experience: {years_exp}
- Skills: {profile_skills}
- Achievements: {achievements}
- LinkedIn: {linkedin}

Rules:
- Write 3 to 4 polished paragraphs.
- Use a banking, fraud, AML, KYC, compliance, risk, or client-service tone.
- Do not invent software-engineering experience.
- Do not mention scalable systems, coding, engineering culture, or shipping software unless the job is actually technical.
- Keep it under 350 words.
- Output only the letter text."""

        try:
            message = client.messages.create(
                model=getattr(settings, "anthropic_model", "claude-sonnet-5"),
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception:
            # Billing/quota/model-access/network failures should not break the app.
            return _fallback_cover_letter(job, user_profile)

    # Unknown providers fail safe and stay free.
    return _fallback_cover_letter(job, user_profile)
