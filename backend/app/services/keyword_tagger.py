"""
Keyword tagger: extracts skills, seniority, and industry labels from job postings.
This is intentionally rule-based so it stays free and works without an AI API.
"""

import re
from typing import Dict, List, Optional

SKILLS_PATTERNS = {
    "Fraud Investigation": r"\bfraud\b|\bfraud prevention\b|\bfraud investigator\b",
    "AML": r"\baml\b|\banti-money laundering\b|\banti money laundering\b",
    "KYC": r"\bkyc\b|\bknow your customer\b",
    "Compliance": r"\bcompliance\b|\bregulatory\b|\bcontrols?\b",
    "Risk Analysis": r"\brisk\b|\brisk analysis\b|\brisk management\b",
    "Transaction Monitoring": r"\btransaction monitoring\b|\bsuspicious activity\b",
    "Due Diligence": r"\bdue diligence\b|\benhanced due diligence\b",
    "Case Documentation": r"\bcase notes?\b|\bdocumentation\b|\baudit-ready\b",
    "Banking": r"\bbanking\b|\bbank\b|\bcredit\b|\bloans?\b|\bfinancial services\b",
    "Customer Service": r"\bcustomer service\b|\bclient service\b|\bclient support\b",
    "Bilingual English/French": r"\bbilingual\b|\bfrench\b|\benglish/french\b|\bfrançais\b",
    "Python": r"\bpython\b",
    "PostgreSQL": r"\bpostgres(?:ql)?\b",
    "AWS": r"\baws\b|\bamazon web services\b",
    "React": r"\breact(?:\.js|js)?\b",
    "TypeScript": r"\btypescript\b",
    "Tailwind": r"\btailwind(?:\s+css)?\b",
    "Django": r"\bdjango\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "SQL": r"\bsql\b",
    "Excel": r"\bexcel\b|\bspreadsheet\b",
    "Microsoft Office": r"\bmicrosoft office\b|\bms office\b|\boffice 365\b",
}

# Order matters. More specific leadership labels must precede broader levels.
SENIORITY_PATTERNS = [
    ("Intern", r"\bintern\b|\binternship\b"),
    ("Junior", r"\bjunior\b|\bjr\.?\b|\bentry[- ]?level\b|\b0[- ]?[12]\s+years?\b"),
    ("Staff", r"\bstaff\b"),
    ("Principal", r"\bprincipal\b"),
    ("Lead", r"\blead\b"),
    ("Manager", r"\bmanager\b|\bmanagement\b"),
    ("Director", r"\bdirector\b"),
    ("Senior", r"\bsenior\b|\bsr\.?\b|\b5\+?\s+years?\b|\b[4-9]\+?\s+years?\b"),
    ("Mid-Level", r"\bmid[- ]?level\b|\bintermediate\b|\b[23][- ][45]\s+years?\b"),
]

# Specific business models precede broad sectors so payments and banking
# software resolves to FinTech rather than the generic Banking category.
INDUSTRY_PATTERNS = [
    ("Financial Crime", r"\bfinancial crime\b|\bfraud\b|\baml\b|\bkyc\b"),
    ("SaaS", r"\bsaas\b|\bsoftware[- ]as[- ]a[- ]service\b"),
    ("FinTech", r"\bfintech\b|\bpayments?\b|\bdigital banking\b"),
    ("Banking", r"\bbanking\b|\bbank\b|\bcredit\b|\bloans?\b|\bfinancial services\b"),
    ("Government", r"\bgovernment\b|\bcra\b|\bcanada revenue\b|\bpublic service\b|\bfederal\b"),
    ("Compliance", r"\bcompliance\b|\bregulatory\b|\brisk\b"),
    ("Customer Operations", r"\bcustomer service\b|\bclient service\b|\boperations\b"),
    ("Technology", r"\bsoftware\b|\bdeveloper\b|\bengineer\b|\bcloud\b|\bapi\b|\bpython\b"),
]


def extract_skills(text: str) -> List[str]:
    text_lower = text.lower()
    return [skill for skill, pattern in SKILLS_PATTERNS.items() if re.search(pattern, text_lower, re.IGNORECASE)]


def detect_seniority(text: str) -> Optional[str]:
    text_lower = text.lower()
    for level, pattern in SENIORITY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return level
    return "Mid-Level"


def detect_industry(text: str) -> Optional[str]:
    text_lower = text.lower()
    for industry, pattern in INDUSTRY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return industry
    return "General"


def _text_has_any(text: str, terms: List[str]) -> bool:
    text_lower = text.lower()
    return any(term.lower() in text_lower for term in terms)


def compute_relevance(job: Dict, user_preferences: Dict) -> float:
    """Score 0..1 measuring how well this job matches user prefs."""
    score = 0.45
    user_preferences = user_preferences or {}

    pref_skills = {str(s).lower() for s in user_preferences.get("skills", [])}
    pref_titles = [str(t).lower() for t in user_preferences.get("preferred_titles", [])]
    pref_locations = [str(l).lower() for l in user_preferences.get("preferred_locations", [])]
    pref_min_salary = user_preferences.get("min_salary", 0) or 0

    job_skills = {str(s).lower() for s in (job.get("skills") or [])}
    job_title = (job.get("title") or "").lower()
    job_location = (job.get("location") or "").lower()
    job_salary_min = job.get("salary_min") or 0
    combined_text = " ".join([
        job_title,
        job_location,
        " ".join(job.get("skills") or []),
        job.get("description") or "",
        job.get("requirements") or "",
    ]).lower()

    matching_skills = pref_skills & job_skills
    skill_match = False
    if pref_skills and job_skills:
        overlap = len(matching_skills) / max(len(pref_skills), 1)
        score += 0.25 * min(overlap, 1.0)
        skill_match = bool(matching_skills)
    elif pref_skills and any(skill in combined_text for skill in pref_skills):
        score += 0.15
        skill_match = True

    title_match = False
    if pref_titles:
        title_match = any(title in job_title for title in pref_titles)
        if title_match:
            score += 0.2
    elif _text_has_any(job_title, ["fraud", "aml", "kyc", "financial crime", "compliance", "risk", "banking"]):
        score += 0.18

    if pref_locations:
        if any(location in job_location for location in pref_locations) or "remote" in job_location:
            score += 0.1
    elif _text_has_any(job_location, ["ottawa", "gatineau", "montreal", "remote", "canada"]):
        score += 0.08

    if pref_min_salary and job_salary_min:
        score += 0.1 if job_salary_min >= pref_min_salary else -0.1

    is_software_role = _text_has_any(
        job_title,
        ["software engineer", "developer", "devops", "frontend", "backend"],
    )
    has_banking_context = _text_has_any(
        combined_text,
        ["fraud", "aml", "kyc", "compliance", "banking", "risk"],
    )
    if is_software_role and not has_banking_context and not skill_match and not title_match:
        score -= 0.25

    return round(min(max(score, 0.0), 1.0), 3)


def tag_job(job_data: Dict, user_preferences: Dict = None) -> Dict:
    """Enrich a job dict with tags, skills, seniority, industry, and relevance."""
    combined_text = " ".join(filter(None, [
        job_data.get("title", ""),
        job_data.get("description", ""),
        job_data.get("requirements", ""),
    ]))

    skills = extract_skills(combined_text)
    seniority = detect_seniority(combined_text)
    industry = detect_industry(combined_text)
    tags = [value for value in {seniority, industry, *skills[:5]} if value]

    job_data["skills"] = skills
    job_data["seniority"] = seniority
    job_data["industry"] = industry
    job_data["tags"] = tags
    job_data["relevance_score"] = compute_relevance({**job_data, "skills": skills}, user_preferences or {})
    return job_data
