"""
Keyword tagger: extracts skills, seniority, and industry labels from job postings
using rule-based NLP. No external API required.
"""
import re
from typing import List, Dict, Tuple, Optional

SKILLS_PATTERNS = {
    # Languages
    "Python": r"\bpython\b",
    "JavaScript": r"\bjavascript\b|\bjs\b",
    "TypeScript": r"\btypescript\b|\bts\b",
    "Java": r"\bjava\b(?!script)",
    "Go": r"\bgolang\b|\b(?<!\w)go(?!\w)",
    "Rust": r"\brust\b",
    "C++": r"\bc\+\+\b|\bcpp\b",
    "C#": r"\bc#\b|\b\.net\b",
    "Ruby": r"\bruby\b|\brails\b",
    "PHP": r"\bphp\b",
    "Swift": r"\bswift\b",
    "Kotlin": r"\bkotlin\b",
    "Scala": r"\bscala\b",
    "R": r"\b(?<!\w)r(?!\w)\s+programming|\brlang\b",
    # Frontend
    "React": r"\breact\.?js\b|\breact\b",
    "Vue": r"\bvue\.?js\b|\bvue\b",
    "Angular": r"\bangular\b",
    "Next.js": r"\bnext\.?js\b",
    "Svelte": r"\bsvelte\b",
    "Tailwind": r"\btailwind\b",
    # Backend / frameworks
    "FastAPI": r"\bfastapi\b",
    "Django": r"\bdjango\b",
    "Flask": r"\bflask\b",
    "Node.js": r"\bnode\.?js\b",
    "Express": r"\bexpress\.?js\b|\bexpress\b",
    "Spring": r"\bspring\s+boot\b|\bspring\b",
    "Laravel": r"\blaravel\b",
    # Data & ML
    "PyTorch": r"\bpytorch\b",
    "TensorFlow": r"\btensorflow\b",
    "scikit-learn": r"\bscikit\b|\bsklearn\b",
    "Pandas": r"\bpandas\b",
    "NumPy": r"\bnumpy\b",
    "Spark": r"\bapache\s+spark\b|\bpyspark\b|\bspark\b",
    "Kafka": r"\bapache\s+kafka\b|\bkafka\b",
    "Airflow": r"\bairflow\b",
    "dbt": r"\bdbt\b",
    # Databases
    "PostgreSQL": r"\bpostgres(?:ql)?\b|\bpg\b",
    "MySQL": r"\bmysql\b",
    "MongoDB": r"\bmongodb\b|\bmongo\b",
    "Redis": r"\bredis\b",
    "Elasticsearch": r"\belasticsearch\b|\belastic\b",
    "Cassandra": r"\bcassandra\b",
    "Snowflake": r"\bsnowflake\b",
    "BigQuery": r"\bbigquery\b",
    "DynamoDB": r"\bdynamodb\b",
    # Cloud & DevOps
    "AWS": r"\baws\b|\bamazon\s+web\s+services\b",
    "GCP": r"\bgcp\b|\bgoogle\s+cloud\b",
    "Azure": r"\bazure\b|\bmicrosoft\s+azure\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "Terraform": r"\bterraform\b",
    "CI/CD": r"\bci[/\-]?cd\b|\bcontinuous\s+integration\b|\bgithub\s+actions\b|\bjenkis\b",
    "Linux": r"\blinux\b|\bubuntu\b|\bdebian\b",
    # Practices
    "REST API": r"\brest(?:ful)?\s+api\b|\brest\s+api\b",
    "GraphQL": r"\bgraphql\b",
    "Microservices": r"\bmicroservices\b",
    "Agile": r"\bagile\b|\bscrum\b",
    "System Design": r"\bsystem\s+design\b",
    "Machine Learning": r"\bmachine\s+learning\b|\bml\b",
    "Data Science": r"\bdata\s+science\b",
    "LLM": r"\bllm\b|\blarge\s+language\s+model\b",
}

SENIORITY_PATTERNS = [
    ("Intern", r"\bintern\b|\binternship\b"),
    ("Junior", r"\bjunior\b|\bjr\.?\b|\bentry[- ]?level\b|\b0[- ]?[12]\s+years?\b"),
    ("Mid-Level", r"\bmid[- ]?level\b|\bintermediate\b|\b[23][- ][45]\s+years?\b"),
    ("Senior", r"\bsenior\b|\bsr\.?\b|\b5\+?\s+years?\b|\b[4-9]\+?\s+years?\b"),
    ("Staff", r"\bstaff\b"),
    ("Principal", r"\bprincipal\b"),
    ("Lead", r"\btech\s+lead\b|\blead\s+engineer\b"),
    ("Manager", r"\bengineering\s+manager\b|\bem\b"),
    ("Director", r"\bdirector\b"),
    ("VP", r"\bvp\b|\bvice\s+president\b"),
]

INDUSTRY_PATTERNS = [
    ("FinTech", r"\bfintech\b|\bfinancial\s+tech\b|\bpayments?\b|\bbanking\b"),
    ("HealthTech", r"\bhealthtech\b|\bhealth\s+tech\b|\bhealthcare\b|\bmedical\b|\behr\b"),
    ("EdTech", r"\bedtech\b|\beducation\s+tech\b|\be-?learning\b"),
    ("E-Commerce", r"\be[- ]?commerce\b|\bretail\b|\bmarketplace\b"),
    ("SaaS", r"\bsaas\b|\bsoftware\s+as\s+a\s+service\b"),
    ("AI/ML", r"\bartificial\s+intelligence\b|\bai[/ ]ml\b|\bmachine\s+learning\b"),
    ("Cybersecurity", r"\bcybersecurity\b|\bsecurity\b|\binfosec\b"),
    ("Gaming", r"\bgaming\b|\bgame\s+development\b"),
    ("Crypto/Web3", r"\bcrypto\b|\bblockchain\b|\bweb3\b|\bdefi\b"),
    ("AdTech", r"\badtech\b|\badvertising\s+tech\b|\bprogrammatic\b"),
    ("DevTools", r"\bdeveloper\s+tools?\b|\bdev\s*tools?\b"),
    ("Cloud", r"\bcloud\s+infrastructure\b|\bcloud\s+platform\b"),
    ("Data Platform", r"\bdata\s+platform\b|\bdata\s+infrastructure\b|\banalytics\s+platform\b"),
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
    return "Software"


def compute_relevance(job: Dict, user_preferences: Dict) -> float:
    """Score 0..1 measuring how well this job matches user prefs."""
    score = 0.5  # neutral baseline
    pref_skills = {s.lower() for s in user_preferences.get("skills", [])}
    pref_titles = [t.lower() for t in user_preferences.get("preferred_titles", [])]
    pref_locations = [l.lower() for l in user_preferences.get("preferred_locations", [])]
    pref_min_salary = user_preferences.get("min_salary", 0)

    job_skills = {s.lower() for s in (job.get("skills") or [])}
    job_title = (job.get("title") or "").lower()
    job_location = (job.get("location") or "").lower()
    job_salary_min = job.get("salary_min") or 0

    # Skills overlap
    if pref_skills and job_skills:
        overlap = len(pref_skills & job_skills) / max(len(pref_skills), 1)
        score += 0.3 * min(overlap, 1.0)

    # Title match
    if pref_titles:
        if any(t in job_title for t in pref_titles):
            score += 0.15

    # Location match
    if pref_locations:
        if any(l in job_location for l in pref_locations) or "remote" in job_location:
            score += 0.1

    # Salary match
    if pref_min_salary and job_salary_min:
        if job_salary_min >= pref_min_salary:
            score += 0.1
        else:
            score -= 0.1

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
    tags = list({seniority, industry, *skills[:5]})

    job_data["skills"] = skills
    job_data["seniority"] = seniority
    job_data["industry"] = industry
    job_data["tags"] = tags
    job_data["relevance_score"] = compute_relevance(
        {**job_data, "skills": skills},
        user_preferences or {},
    )
    return job_data
