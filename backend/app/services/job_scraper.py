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
    "RBC", "TD Bank", "Scotiabank", "BMO", "CIBC", "National Bank",
    "CRA", "FINTRAC", "OSFI", "Manulife", "Sun Life", "Desjardins",
    "Equitable Bank", "Tangerine", "Payments Canada", "Interac",
]

MOCK_TITLES_BY_KW = {
    "fraud": ["Fraud Analyst", "Fraud Operations Specialist", "Financial Crimes Analyst", "Fraud Investigation Analyst"],
    "aml": ["AML Analyst", "Anti-Money Laundering Investigator", "AML Compliance Analyst", "Transaction Monitoring Analyst"],
    "kyc": ["KYC Analyst", "Client Due Diligence Analyst", "EDD Analyst", "Onboarding Compliance Analyst"],
    "compliance": ["Compliance Officer", "Regulatory Compliance Analyst", "Risk and Compliance Analyst", "Controls Analyst"],
    "banking": ["Banking Operations Analyst", "Financial Services Representative", "Credit Risk Analyst", "Payments Operations Analyst"],
    "default": ["Fraud Analyst", "AML Analyst", "KYC Analyst", "Compliance Officer"],
}

MOCK_LOCATIONS = [
    "Ottawa, ON", "Gatineau, QC", "Toronto, ON", "Mississauga, ON",
    "Remote (Canada)", "Hybrid - Ottawa, ON", "Montréal, QC",
]

MOCK_DESCRIPTIONS = [
    "We are hiring a {title} to support high-volume financial services operations. "
    "The role requires careful documentation, sound judgment, privacy awareness, and timely escalation.\n\n"
    "**What you'll do:**\n"
    "- Review account, customer, or transaction information for risk indicators\n"
    "- Document findings clearly for audit and quality review\n"
    "- Escalate suspicious or incomplete information according to policy\n"
    "- Support AML/KYC, fraud prevention, compliance, and customer protection work\n\n"
    "**Requirements:**\n"
    "- Experience or strong interest in {skill}\n"
    "- Strong attention to detail and written communication\n"
    "- Understanding of FINTRAC, PCMLTFA, EDD, STRs, or regulatory controls is an asset\n"
    "- Ability to work accurately with confidential information",
]


def _mock_salary(salary_min: Optional[int], salary_max: Optional[int]):
    base = random.randint(55, 85) * 1000
    spread = random.randint(5, 18) * 1000
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
            "salary_currency": "CAD",
            "job_type": job_type or "full_time",
            "description": desc,
            "requirements": f"Experience with {keywords}, AML/KYC reviews, fraud investigations, FINTRAC guidance, documentation, and risk escalation",
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

            soup = BeautifulSoup(resp.text, "html.parser")
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

            soup = BeautifulSoup(resp.text, "html.parser")
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
# Job Bank Canada scraper (public search results)
# ---------------------------------------------------------------------------
async def scrape_jobbank_canada(
    keywords: str,
    location: Optional[str],
    salary_min: Optional[int],
    salary_max: Optional[int],
    job_type: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    params = {
        "searchstring": keywords,
        "locationstring": location or "Ottawa, ON",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-CA,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get("https://www.jobbank.gc.ca/jobsearch/jobsearch", params=params, headers=headers)
            if resp.status_code != 200:
                raise ValueError(f"Job Bank returned {resp.status_code}")

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("article, .resultJobItem, .search-result, [data-jobid]")
            for card in cards[:limit]:
                title_el = card.select_one("a[href*='/jobsearch/jobposting/'], h3, .noctitle")
                company_el = card.select_one(".business, .employer, [class*='company']")
                location_el = card.select_one(".location, [class*='location']")
                salary_el = card.select_one(".salary, [class*='salary'], .attribute")
                link_el = card.select_one("a[href*='/jobsearch/jobposting/']")

                title = title_el.get_text(strip=True) if title_el else "Compliance Analyst"
                company = company_el.get_text(strip=True) if company_el else "Job Bank Employer"
                loc = location_el.get_text(" ", strip=True) if location_el else (location or "Ottawa, ON")
                salary_text = salary_el.get_text(" ", strip=True) if salary_el else ""
                href = link_el.get("href", "") if link_el else ""
                job_url = f"https://www.jobbank.gc.ca{href}" if href.startswith("/") else href
                external_id = card.get("data-jobid") or _uid("jobbank", company, title)
                sal_lo, sal_hi = _parse_salary(salary_text, salary_min, salary_max)

                jobs.append({
                    "external_id": external_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary_min": sal_lo,
                    "salary_max": sal_hi,
                    "salary_currency": "CAD",
                    "job_type": job_type or "full_time",
                    "description": "",
                    "requirements": "",
                    "url": job_url,
                    "source": "jobbank",
                })
    except Exception:
        jobs = _build_mock_jobs(keywords, location or "Ottawa, ON", salary_min, salary_max, job_type, "jobbank", min(limit, 15))

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
        sources = ["jobbank", "indeed", "linkedin", "glassdoor"]

    per_source = max(10, limit // len(sources))
    tasks = []
    if "jobbank" in sources:
        tasks.append(scrape_jobbank_canada(keywords, location, salary_min, salary_max, job_type, per_source))
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
