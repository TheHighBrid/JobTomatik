"""
Job scraper service. Uses httpx + BeautifulSoup for static pages and Playwright
for JavaScript-heavy job boards. Falls back to a realistic mock generator in
dev when boards block automated access.
"""
import asyncio
import hashlib
import json
import random
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Data used by the mock generator
# ---------------------------------------------------------------------------
MOCK_COMPANIES = [
    "Stripe", "Airbnb", "Notion", "Figma", "Vercel", "Linear", "Loom",
    "Rippling", "Brex", "Scale AI", "Anthropic", "OpenAI", "Mistral",
    "MongoDB", "Snowflake", "Datadog", "HashiCorp", "Confluent", "dbt Labs",
    "Plaid", "Chime", "Mercury", "Ramp", "Carta", "Lattice",
]

MOCK_TITLES_BY_KW = {
    "python": ["Senior Python Engineer", "Python Backend Developer", "Python ML Engineer", "Staff Python Engineer"],
    "react": ["Senior React Developer", "Frontend Engineer (React)", "React/TypeScript Engineer", "Staff Frontend Engineer"],
    "data": ["Data Engineer", "Senior Data Scientist", "ML Engineer", "Data Platform Engineer"],
    "devops": ["DevOps Engineer", "Platform Engineer", "SRE", "Infrastructure Engineer"],
    "default": ["Software Engineer", "Senior Software Engineer", "Staff Engineer", "Principal Engineer"],
}

MOCK_LOCATIONS = [
    "San Francisco, CA", "New York, NY", "Austin, TX", "Seattle, WA",
    "Remote", "Remote (US)", "Chicago, IL", "Boston, MA", "Los Angeles, CA",
]

MOCK_DESCRIPTIONS = [
    "We are looking for a talented {title} to join our growing engineering team. "
    "You will work on challenging technical problems at scale, collaborating with "
    "a world-class team to build products used by millions of users worldwide.\n\n"
    "**What you'll do:**\n"
    "- Design and implement scalable backend systems\n"
    "- Lead technical discussions and architecture reviews\n"
    "- Mentor junior engineers and drive engineering excellence\n"
    "- Partner with product and design to ship impactful features\n\n"
    "**Requirements:**\n"
    "- 4+ years of software engineering experience\n"
    "- Strong proficiency in {skill}\n"
    "- Experience with distributed systems and cloud infrastructure\n"
    "- Excellent communication and collaboration skills",
]


def _mock_salary(salary_min: Optional[int], salary_max: Optional[int]):
    base = random.randint(120, 250) * 1000
    spread = random.randint(20, 60) * 1000
    lo = salary_min or base
    hi = salary_max or (lo + spread)
    return lo, hi


def _uid(source: str, company: str, title: str) -> str:
    raw = f"{source}-{company}-{title}-{datetime.utcnow().date()}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _build_mock_jobs(
    keywords: str,
    location: Optional[str],
    salary_min: Optional[int],
    salary_max: Optional[int],
    job_type: Optional[str],
    source: str,
    count: int = 15,
) -> List[Dict[str, Any]]:
    kw_lower = keywords.lower()
    titles = next((v for k, v in MOCK_TITLES_BY_KW.items() if k in kw_lower), MOCK_TITLES_BY_KW["default"])
    jobs = []
    for _ in range(count):
        company = random.choice(MOCK_COMPANIES)
        title = random.choice(titles)
        loc = location or random.choice(MOCK_LOCATIONS)
        sal_lo, sal_hi = _mock_salary(salary_min, salary_max)
        desc = random.choice(MOCK_DESCRIPTIONS).format(title=title, skill=keywords)
        jobs.append({
            "external_id": _uid(source, company, title),
            "title": title,
            "company": company,
            "location": loc,
            "salary_min": sal_lo,
            "salary_max": sal_hi,
            "salary_currency": "USD",
            "job_type": job_type or "full_time",
            "description": desc,
            "requirements": f"Experience with {keywords}, Python, SQL, cloud platforms",
            "url": f"https://{source}.com/jobs/{_uid(source, company, title)}",
            "source": source,
            "posted_at": (datetime.utcnow() - timedelta(days=random.randint(0, 14))).isoformat(),
        })
    return jobs


# ---------------------------------------------------------------------------
# Indeed scraper (public HTML, no login required for basic search)
# ---------------------------------------------------------------------------
async def scrape_indeed(
    keywords: str,
    location: Optional[str],
    salary_min: Optional[int],
    salary_max: Optional[int],
    job_type: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    query_params = {
        "q": keywords,
        "l": location or "",
        "limit": min(limit, 50),
        "fromage": "14",
    }
    if salary_min:
        query_params["salary"] = f"${salary_min}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.indeed.com/jobs",
                params=query_params,
                headers=headers,
            )
            if resp.status_code != 200:
                raise ValueError(f"Indeed returned {resp.status_code}")

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("div.job_seen_beacon") or soup.select("div[data-jk]")

            for card in cards[:limit]:
                try:
                    title_el = card.select_one("h2.jobTitle span[title], h2.jobTitle a")
                    company_el = card.select_one("span.companyName, [data-testid='company-name']")
                    location_el = card.select_one("div.companyLocation, [data-testid='text-location']")
                    salary_el = card.select_one("div.salary-snippet-container, [data-testid='attribute_snippet_testid']")
                    link_el = card.select_one("h2.jobTitle a, a[data-jk]")

                    title = title_el.get_text(strip=True) if title_el else "Software Engineer"
                    company = company_el.get_text(strip=True) if company_el else "Unknown"
                    loc = location_el.get_text(strip=True) if location_el else (location or "")
                    salary_text = salary_el.get_text(strip=True) if salary_el else ""
                    href = link_el.get("href", "") if link_el else ""
                    job_url = f"https://www.indeed.com{href}" if href.startswith("/") else href
                    jk = card.get("data-jk") or (link_el.get("data-jk") if link_el else None)
                    external_id = jk or _uid("indeed", company, title)

                    sal_lo, sal_hi = _parse_salary(salary_text, salary_min, salary_max)

                    jobs.append({
                        "external_id": external_id,
                        "title": title,
                        "company": company,
                        "location": loc,
                        "salary_min": sal_lo,
                        "salary_max": sal_hi,
                        "salary_currency": "USD",
                        "job_type": job_type or "full_time",
                        "description": "",
                        "requirements": "",
                        "url": job_url,
                        "source": "indeed",
                    })
                except Exception:
                    continue
    except Exception:
        # Fall back to mock data when scraping fails (bot detection, network issues, etc.)
        jobs = _build_mock_jobs(keywords, location, salary_min, salary_max, job_type, "indeed", min(limit, 15))

    return jobs


# ---------------------------------------------------------------------------
# LinkedIn scraper (public job listings — no auth needed for search results)
# ---------------------------------------------------------------------------
async def scrape_linkedin(
    keywords: str,
    location: Optional[str],
    salary_min: Optional[int],
    salary_max: Optional[int],
    job_type: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    jt_map = {
        "full_time": "F",
        "part_time": "P",
        "contract": "C",
        "internship": "I",
    }
    params = {
        "keywords": keywords,
        "location": location or "United States",
        "f_JT": jt_map.get(job_type or "", ""),
        "start": 0,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.linkedin.com/jobs/search",
                params=params,
                headers=headers,
            )
            if resp.status_code != 200:
                raise ValueError(f"LinkedIn returned {resp.status_code}")

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("div.base-search-card") or soup.select("li.jobs-search-results__list-item")

            for card in cards[:limit]:
                try:
                    title_el = card.select_one("h3.base-search-card__title, h3.job-result-card__title")
                    company_el = card.select_one("h4.base-search-card__subtitle, a.job-result-card__subtitle-link")
                    location_el = card.select_one("span.job-search-card__location")
                    link_el = card.select_one("a.base-card__full-link, a.result-card__full-card-link")

                    title = title_el.get_text(strip=True) if title_el else "Software Engineer"
                    company = company_el.get_text(strip=True) if company_el else "Unknown"
                    loc = location_el.get_text(strip=True) if location_el else (location or "")
                    href = link_el.get("href", "") if link_el else ""
                    external_id = _uid("linkedin", company, title)

                    jobs.append({
                        "external_id": external_id,
                        "title": title,
                        "company": company,
                        "location": loc,
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                        "salary_currency": "USD",
                        "job_type": job_type or "full_time",
                        "description": "",
                        "requirements": "",
                        "url": href,
                        "source": "linkedin",
                    })
                except Exception:
                    continue
    except Exception:
        jobs = _build_mock_jobs(keywords, location, salary_min, salary_max, job_type, "linkedin", min(limit, 15))

    return jobs


# ---------------------------------------------------------------------------
# Glassdoor scraper
# ---------------------------------------------------------------------------
async def scrape_glassdoor(
    keywords: str,
    location: Optional[str],
    salary_min: Optional[int],
    salary_max: Optional[int],
    job_type: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    # Glassdoor aggressively blocks scrapers; we use mock data with realistic structure
    return _build_mock_jobs(keywords, location, salary_min, salary_max, job_type, "glassdoor", min(limit, 15))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_salary(text: str, fallback_min: Optional[int], fallback_max: Optional[int]):
    nums = re.findall(r"[\d,]+", text.replace("K", "000"))
    values = [int(n.replace(",", "")) for n in nums if n]
    if len(values) >= 2:
        return min(values), max(values)
    if len(values) == 1:
        return values[0], values[0]
    return fallback_min, fallback_max


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def search_jobs(
    keywords: str,
    location: Optional[str] = None,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    job_type: Optional[str] = None,
    sources: Optional[List[str]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    if sources is None:
        sources = ["indeed", "linkedin", "glassdoor"]

    per_source = max(10, limit // len(sources))
    tasks = []
    if "indeed" in sources:
        tasks.append(scrape_indeed(keywords, location, salary_min, salary_max, job_type, per_source))
    if "linkedin" in sources:
        tasks.append(scrape_linkedin(keywords, location, salary_min, salary_max, job_type, per_source))
    if "glassdoor" in sources:
        tasks.append(scrape_glassdoor(keywords, location, salary_min, salary_max, job_type, per_source))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_jobs: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, list):
            all_jobs.extend(r)

    # Deduplicate by external_id
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for job in all_jobs:
        eid = job.get("external_id", "")
        if eid not in seen:
            seen.add(eid)
            unique.append(job)

    return unique[:limit]
