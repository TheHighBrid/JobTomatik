"""
Cover letter generator using the Anthropic Claude API.
Falls back to a template when no API key is configured.
"""
from typing import Dict, Optional
import anthropic
from app.config import get_settings

settings = get_settings()


FALLBACK_TEMPLATE = """Dear Hiring Manager,

I am writing to express my strong interest in the {title} position at {company}. With my background in {skills}, I am confident I would make a meaningful contribution to your team.

Throughout my career, I have developed deep expertise in {primary_skill} and have a proven track record of delivering high-quality software solutions. I am particularly drawn to {company} because of its reputation for technical excellence and impactful products.

In my previous roles, I have:
- Built scalable systems handling millions of requests
- Collaborated closely with cross-functional teams to ship features on time
- Mentored junior engineers and contributed to engineering culture

I am excited about the opportunity to bring my skills in {skills} to {company} and help drive the team's goals forward. I look forward to discussing how my background aligns with your needs.

Thank you for considering my application.

Best regards,
{name}
"""


async def generate_cover_letter(
    job: Dict,
    user_profile: Dict,
) -> str:
    title = job.get("title", "Software Engineer")
    company = job.get("company", "your company")
    description = job.get("description", "")
    requirements = job.get("requirements", "")
    skills = ", ".join(job.get("skills", [])[:8]) or "software engineering"
    primary_skill = (job.get("skills") or ["software engineering"])[0]
    name = user_profile.get("full_name", "Applicant")
    current_role = user_profile.get("current_role", "Software Engineer")
    years_exp = user_profile.get("years_experience", "several")
    profile_skills = ", ".join((user_profile.get("skills") or [])[:6]) or skills
    achievements = user_profile.get("key_achievements", "")
    linkedin = user_profile.get("linkedin_url", "")

    if not settings.anthropic_api_key:
        return FALLBACK_TEMPLATE.format(
            title=title,
            company=company,
            skills=profile_skills or skills,
            primary_skill=primary_skill,
            name=name,
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

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
- Write a professional 3-4 paragraph cover letter
- Open with a strong hook that references the specific role and company
- Highlight 2-3 concrete achievements aligned with the job requirements
- Show genuine enthusiasm for this specific company (not generic praise)
- Close with a clear call to action
- Keep it under 400 words
- Do NOT include "Dear Hiring Manager" as the salutation — use a natural opener
- Sign off with the applicant's name
- Do NOT use placeholder text like [X years] — use the provided data

Write only the cover letter text, no meta-commentary."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()
