"""
Cover letter generator.
AI_PROVIDER controls which backend is used:
  template  — free, no API key needed (default)
  anthropic — Anthropic Claude API
  gemini    — Google Gemini Flash-Lite (cheap)
"""
from typing import Dict, Optional

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None

from app.config import get_settings

settings = get_settings()


BANKING_TEMPLATE = """\
{opening}

With {years_exp} years of experience in {domain}, I bring hands-on expertise in {primary_skill} and a strong track record in {secondary_skill}. My background includes conducting thorough investigations, preparing detailed case documentation, and working closely with compliance and regulatory teams to meet reporting obligations under FINTRAC and PCMLTFA requirements.

In my most recent role as {current_role}, I {achievement_sentence} I am comfortable working in bilingual environments and producing reports in both English and French when required.

I am drawn to {company} because of its commitment to robust financial crime prevention and its reputation as a responsible institution. I am eager to contribute my analytical skills, attention to detail, and knowledge of AML/KYC frameworks to support your compliance program.

Thank you for considering my application. I look forward to the opportunity to discuss how my background aligns with your team's needs.

Best regards,
{name}
"""

_OPENINGS = [
    "I am pleased to apply for the {title} position at {company}.",
    "I am writing to express my strong interest in the {title} role at {company}.",
    "Please accept this letter as my application for the {title} opportunity at {company}.",
]

_ACHIEVEMENTS = [
    "identified and escalated over 40 suspicious transaction reports (STRs) within prescribed timelines.",
    "conducted KYC reviews on high-risk client accounts, reducing onboarding risk by strengthening due-diligence controls.",
    "supported internal audits by preparing comprehensive AML documentation and transaction monitoring reports.",
    "reviewed complex multi-jurisdictional transactions to detect layering and structuring patterns.",
]

_DOMAINS = {
    "fraud": ("financial crime and fraud investigation", "fraud detection", "case documentation and STR filing"),
    "aml": ("AML compliance and transaction monitoring", "AML/CTF frameworks", "risk-based client due diligence"),
    "kyc": ("KYC and customer due diligence", "know-your-customer processes", "enhanced due diligence (EDD)"),
    "compliance": ("regulatory compliance", "compliance monitoring", "policy implementation and audit support"),
    "banking": ("banking and financial services compliance", "AML/KYC", "regulatory reporting"),
}


def _free_template(job: Dict, profile: Dict) -> str:
    import random

    title = job.get("title", "Compliance Analyst")
    company = job.get("company", "your organization")
    skills = job.get("skills") or []
    kw = " ".join(skills + [title]).lower()

    domain_key = next((k for k in _DOMAINS if k in kw), "banking")
    domain, primary_skill, secondary_skill = _DOMAINS[domain_key]

    name = profile.get("full_name") or "Applicant"
    current_role = profile.get("current_role") or "Financial Crime Analyst"
    years_exp = profile.get("years_experience") or "several"
    achievement = profile.get("key_achievements") or random.choice(_ACHIEVEMENTS)
    achievement_sentence = achievement if achievement.endswith(".") else achievement + "."

    opening = random.choice(_OPENINGS).format(title=title, company=company)

    return BANKING_TEMPLATE.format(
        opening=opening,
        years_exp=years_exp,
        domain=domain,
        primary_skill=primary_skill,
        secondary_skill=secondary_skill,
        current_role=current_role,
        achievement_sentence=achievement_sentence,
        company=company,
        name=name,
    )


async def _anthropic_generate(job: Dict, profile: Dict) -> str:
    if _anthropic is None:
        raise ImportError("anthropic package not installed")

    title = job.get("title", "Compliance Analyst")
    company = job.get("company", "your organization")
    description = job.get("description", "")
    requirements = job.get("requirements", "")
    skills = ", ".join((job.get("skills") or [])[:8]) or "AML, KYC, fraud investigation"
    name = profile.get("full_name") or "Applicant"
    current_role = profile.get("current_role") or "Financial Crime Analyst"
    years_exp = profile.get("years_experience") or "several"
    profile_skills = ", ".join((profile.get("skills") or [])[:6]) or skills
    achievements = profile.get("key_achievements") or ""
    linkedin = profile.get("linkedin_url") or ""

    prompt = f"""Write a compelling, personalized cover letter for this job application.

**Job Details:**
- Position: {title}
- Company: {company}
- Job Description: {description[:1500]}
- Key Requirements: {requirements[:800]}
- Required Skills: {skills}

**Applicant Profile:**
- Name: {name}
- Current/Most Recent Role: {current_role}
- Years of Experience: {years_exp}
- Skills: {profile_skills}
- Key Achievements: {achievements}
- LinkedIn: {linkedin}

**Instructions:**
- Write a professional 3-4 paragraph cover letter for a banking/compliance/financial crime role
- Open with a direct statement of interest in the specific role and company
- Highlight relevant AML, KYC, fraud investigation, or compliance achievements
- Reference Canadian regulatory context (FINTRAC, PCMLTFA) if relevant
- Close with a clear call to action
- Keep it under 400 words
- Sign off with the applicant's name
- Do NOT use placeholder text like [X years] — use the actual data provided

Write only the cover letter text, no meta-commentary."""

    client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


async def _gemini_generate(job: Dict, profile: Dict) -> str:
    try:
        import httpx
    except ImportError:
        raise ImportError("httpx package not installed")

    title = job.get("title", "Compliance Analyst")
    company = job.get("company", "your organization")
    description = job.get("description", "")
    skills = ", ".join((job.get("skills") or [])[:8]) or "AML, KYC, fraud investigation"
    name = profile.get("full_name") or "Applicant"
    current_role = profile.get("current_role") or "Financial Crime Analyst"
    years_exp = profile.get("years_experience") or "several"
    profile_skills = ", ".join((profile.get("skills") or [])[:6]) or skills
    achievements = profile.get("key_achievements") or ""

    prompt = (
        f"Write a 3-4 paragraph professional cover letter for a {title} position at {company}. "
        f"The applicant is {name}, currently working as {current_role} with {years_exp} years of experience. "
        f"Key skills: {profile_skills}. Achievements: {achievements}. "
        f"Job description excerpt: {description[:800]}. "
        f"Focus on AML/KYC/fraud compliance experience, Canadian regulatory context (FINTRAC), "
        f"and close with a call to action. Under 400 words. Sign off as {name}."
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def generate_cover_letter(job: Dict, user_profile: Dict) -> str:
    provider = (settings.ai_provider or "template").lower()

    if provider == "anthropic" and settings.anthropic_api_key and _anthropic is not None:
        try:
            return await _anthropic_generate(job, user_profile)
        except Exception:
            pass

    if provider == "gemini" and settings.gemini_api_key:
        try:
            return await _gemini_generate(job, user_profile)
        except Exception:
            pass

    return _free_template(job, user_profile)
