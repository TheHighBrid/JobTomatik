"""
Cover letter generator with template, Anthropic, and Gemini providers.

The free template is intentionally tuned for Canadian banking, fraud, AML/KYC,
and compliance roles. Paid providers fall back to the template if they fail.
"""
from typing import Any, Dict, List
import importlib
import importlib.util

import httpx

from app.config import get_settings

settings = get_settings()

BANKING_KEYWORDS = {
    "aml": ["aml", "anti-money laundering", "money laundering", "fintrac", "pcmltfa", "str", "suspicious transaction"],
    "kyc": ["kyc", "know your customer", "customer due diligence", "cdd", "edd", "enhanced due diligence"],
    "fraud": ["fraud", "chargeback", "dispute", "investigation", "identity theft", "financial crime"],
    "compliance": ["compliance", "regulatory", "osfi", "risk", "audit", "policy", "controls"],
    "banking": ["bank", "banking", "credit", "loan", "mortgage", "wealth", "insurance", "financial services"],
}

DOMAIN_LINES = {
    "aml": "I bring a strong understanding of AML monitoring, FINTRAC expectations, PCMLTFA obligations, suspicious transaction indicators, and escalation discipline.",
    "kyc": "I am comfortable with KYC reviews, customer due diligence, enhanced due diligence, documentation quality, and risk-based decision making.",
    "fraud": "I bring a practical fraud-prevention mindset, attention to transaction patterns, evidence gathering, and clear investigation notes.",
    "compliance": "I understand the importance of regulatory controls, audit-ready documentation, policy adherence, and timely escalation of risk.",
    "banking": "I am motivated by customer-focused financial services work that requires accuracy, confidentiality, sound judgment, and strong operational discipline.",
    "general": "I bring careful judgment, clear communication, strong documentation habits, and a practical focus on doing high-volume work accurately.",
}


def _as_text(values: Any, limit: int = 8) -> str:
    if isinstance(values, list):
        return ", ".join(str(item) for item in values[:limit] if item)
    return str(values or "").strip()


def _job_blob(job: Dict[str, Any]) -> str:
    parts = [
        job.get("title"),
        job.get("company"),
        job.get("description"),
        job.get("requirements"),
        _as_text(job.get("skills")),
        _as_text(job.get("tags")),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _detect_domains(job: Dict[str, Any]) -> List[str]:
    blob = _job_blob(job)
    domains = [domain for domain, words in BANKING_KEYWORDS.items() if any(word in blob for word in words)]
    return domains or ["general"]


def _template_cover_letter(job: Dict[str, Any], user_profile: Dict[str, Any]) -> str:
    title = job.get("title") or "the role"
    company = job.get("company") or "your organization"
    name = user_profile.get("full_name") or "Applicant"
    current_role = user_profile.get("current_role") or user_profile.get("headline") or "candidate"
    years_exp = user_profile.get("years_experience") or user_profile.get("years_of_experience") or "several"
    profile_skills = _as_text(user_profile.get("skills")) or _as_text(job.get("skills")) or "investigation, documentation, customer service, and compliance"
    achievements = user_profile.get("key_achievements") or user_profile.get("achievements") or ""
    domains = _detect_domains(job)
    domain_text = " ".join(DOMAIN_LINES[d] for d in domains[:3])

    achievement_sentence = (
        f" A highlight from my background is {achievements}." if achievements else " I am consistent about keeping work organized, accurate, and easy for managers or auditors to review."
    )

    return f"""Dear Hiring Manager,

I am excited to apply for the {title} position at {company}. My background as a {current_role}, combined with {years_exp} years of relevant experience, has prepared me to contribute in a role that requires accuracy, judgment, confidentiality, and dependable follow-through.

{domain_text} My strengths include {profile_skills}. I pay close attention to details, document decisions clearly, and understand the importance of escalating unusual activity or incomplete information quickly and professionally.{achievement_sentence}

I would welcome the opportunity to bring this practical, compliance-minded approach to {company}. Thank you for considering my application; I would be glad to discuss how my experience aligns with your team’s needs.

Best regards,
{name}
""".strip()


def _build_prompt(job: Dict[str, Any], user_profile: Dict[str, Any]) -> str:
    title = job.get("title", "the role")
    company = job.get("company", "the company")
    description = str(job.get("description") or "")[:1800]
    requirements = str(job.get("requirements") or "")[:1000]
    skills = _as_text(job.get("skills"))
    domains = ", ".join(_detect_domains(job))

    return f"""Write a concise, professional cover letter for a Canadian banking/compliance/fraud job application.

Job:
- Title: {title}
- Company: {company}
- Domain keywords detected: {domains}
- Description: {description}
- Requirements: {requirements}
- Skills: {skills}

Applicant:
- Name: {user_profile.get('full_name', 'Applicant')}
- Current role: {user_profile.get('current_role', user_profile.get('headline', 'Candidate'))}
- Years of experience: {user_profile.get('years_experience', user_profile.get('years_of_experience', 'several'))}
- Skills: {_as_text(user_profile.get('skills'))}
- Achievements: {user_profile.get('key_achievements', user_profile.get('achievements', ''))}

Requirements:
- 3 to 4 short paragraphs.
- Use AML/KYC/fraud/compliance language only when relevant.
- If relevant, mention FINTRAC, PCMLTFA, suspicious transaction reporting, EDD, fraud investigation, regulatory controls, or audit-ready documentation naturally.
- Do not use software-engineering phrases such as scalable systems, millions of requests, engineering culture, or shipping features.
- No placeholders or bracketed text.
- Return only the cover letter.
"""


async def _generate_with_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, params={"key": settings.gemini_api_key}, json=payload)
        response.raise_for_status()
        data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def generate_cover_letter(job: Dict, user_profile: Dict) -> str:
    provider = (settings.ai_provider or "template").lower()
    fallback = _template_cover_letter(job, user_profile)

    if provider == "template":
        return fallback

    prompt = _build_prompt(job, user_profile)

    if provider == "anthropic" and settings.anthropic_api_key:
        if importlib.util.find_spec("anthropic") is None:
            return fallback
        anthropic = importlib.import_module("anthropic")
        try:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            message = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception:
            return fallback

    if provider == "gemini" and settings.gemini_api_key:
        try:
            return await _generate_with_gemini(prompt)
        except Exception:
            return fallback

    return fallback
