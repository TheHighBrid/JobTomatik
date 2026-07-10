"""
Job scraper service.

The scraper now separates job discovery from application automation. It does not
pretend listing pages are application forms. Job Bank postings are enriched into
one of these methods: external_url, email, manual. LinkedIn/Indeed are kept as
discovery-only unless a future connector provides a real application target.
"""

import asyncio
import hashlib
import random
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.services.apply_resolver import resolve_application_method

settings = get_settings()

BANKING_COMPANIES = [
    "RBC", "TD Bank", "Scotiabank", "BMO", "CIBC", "Tangerine",
    "Desjardins", "National Bank", "EQ Bank", "CRA", "FINTRAC",
    "Payments Canada", "Alterna Savings", "Export Development Canada",
    "Canada Post", "Global Affairs Canada",
]

MOCK_TITLES_BY_KW = {
    "fraud": ["Fraud Analyst", "Bilingual Fraud Analyst", "Fraud Prevention Specialist", "Fraud Investigator", "Transaction Monitoring Analyst"],
    "aml": ["AML Analyst", "Anti-Money Laundering Investigator", "Financial Crime Analyst", "KYC Compliance Analyst", "Enhanced Due Diligence Analyst"],
    "kyc": ["KYC Compliance Officer", "Client Due Diligence Analyst", "Account Review Analyst", "Compliance Operations Analyst"],
    "banking": ["Banking Risk Analyst", "Credit Risk Analyst", "Client Resolution Specialist", "Quality Assurance Analyst, Banking", "Account Administration Officer"],
    "default": ["Fraud Analyst", "KYC Compliance Analyst", "AML Investigator", "Risk Mitigation Specialist", "Bilingual Banking Compliance Analyst"],
}

MOCK_LOCATIONS = ["Ottawa, ON", "Gatineau, QC", "Montreal, QC", "Toronto, ON", "Remote, Canada", "Hybrid, Ottawa, ON"]

MOCK_DESCRIPTIONS = [
    "We are seeking a detail-oriented {title} to support fraud prevention, account monitoring, compliance review, and client protection work. "
    "This role requires strong judgment, accurate documentation, and the ability to review sensitive financial information in a high-trust environment.\n\n"
    "What you'll do:\n"
    "- Review transactions, accounts, and client activity for suspicious patterns\n"
    "- Document findings clearly and maintain audit-ready case notes\n"
    "- Support KYC, AML, fraud-prevention, and risk controls\n"
    "- Communicate professionally with clients and internal teams\n"
    "- Escalate suspicious activity and support investigation workflows\n\n"
    "Requirements:\n"
    "- Experience in banking, fraud, AML, KYC, risk, or compliance\n"
    "- Strong attention to detail and documentation skills\n"
    "- Bilingual English/French communication is an asset\n"
    "- Ability to handle confidential information professionally\n"
    "- Strong proficiency in {skill}"
]


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8,fr;q=0.7",
    }


def _uid(source: str, company: str, title: str, url: str = "") -> str:
    raw = f"{source}-{company}-{title}-{url or datetime.utcnow().date()}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _mock_salary(salary_min: Optional[int], salary_max: Optional[int]):
    base = random.randint(55, 85) * 1000
    spread = random.randint(8, 22) * 1000
    lo = salary_min or base
    hi = salary_max or (lo + spread)
    return lo, hi


def _build_mock_jobs(keywords: str, location: Optional[str], salary_min: Optional[int], salary_max: Optional[int], job_type: Optional[str], source: str, count: int = 15) -> List[Dict[str, Any]]:
    kw_lower = keywords.lower()
    titles = next((v for k, v in MOCK_TITLES_BY_KW.items() if k in kw_lower), MOCK_TITLES_BY_KW["default"])
    jobs = []
    for _ in range(count):
        company = random.choice(BANKING_COMPANIES)
        title = random.choice(titles)
        loc = location or random.choice(MOCK_LOCATIONS)
        sal_lo, sal_hi = _mock_salary(salary_min, salary_max)
        desc = random.choice(MOCK_DESCRIPTIONS).format(title=title, skill=keywords)
        url = f"https://example.com/jobs/{_uid(source, company, title)}"
        jobs.append({
            "external_id": _uid(source, company, title, url),
            "title": title,
            "company": company,
            "location": loc,
            "salary_min": sal_lo,
            "salary_max": sal_hi,
            "salary_currency": "CAD",
            "job_type": job_type or "full_time",
            "description": desc,
            "requirements": f"Experience with {keywords}, fraud review, KYC, AML, banking compliance, case documentation",
            "url": url,
            "source": source if source in {"linkedin", "indeed", "glassdoor", "jobbank", "manual"} else "manual",
            "posted_at": (datetime.utcnow() - timedelta(days=random.randint(0, 14))).isoformat(),
            "raw_data": {"application_method": "manual", "reason": "mock job"},
        })
    return jobs


def _fallback_or_empty(keywords: str, location: Optional[str], salary_min: Optional[int], salary_max: Optional[int], job_type: Optional[str], source: str, limit: int) -> List[Dict[str, Any]]:
    if getattr(settings, "dev_mock_jobs", False):
        return _build_mock_jobs(keywords, location, salary_min, salary_max, job_type, source, min(limit, 15))
    return []


def _parse_salary(text: str, fallback_min: Optional[int], fallback_max: Optional[int]):
    if not text:
        return fallback_min, fallback_max
    cleaned = text.replace(",", "").replace("$", "")
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*([kK])?", cleaned)
    values: List[int] = []
    for raw, suffix in matches:
        value = float(raw)
        if suffix.lower() == "k":
            value *= 1000
        elif value < 1000 and "hour" not in cleaned.lower():
            value *= 1000
        values.append(int(value))
    yearly_values = [v for v in values if v >= 20000]
    if len(yearly_values) >= 2:
        return min(yearly_values), max(yearly_values)
    if len(yearly_values) == 1:
        return yearly_values[0], yearly_values[0]
    return fallback_min, fallback_max


def _jobbank_url(href: str) -> Optional[str]:
    """Return an absolute Job Bank posting URL, or None if href is missing/invalid."""
    if not href or href.startswith("?") or href.startswith("#"):
        return None
    if href.startswith("/"):
        url = f"https://www.jobbank.gc.ca{href}"
        # Must be an individual posting, not the search results page
        if "/jobposting/" in url or "/offredemploi/" in url:
            return url
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return href
    except Exception:
        pass
    return None


def _looks_relevant(title: str, text: str, keywords: str) -> bool:
    hay = f"{title} {text}".lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", keywords.lower()) if len(t) >= 3]
    if not tokens:
        return True
    return any(t in hay for t in tokens)


async def scrape_jobbank(keywords: str, location: Optional[str], salary_min: Optional[int], salary_max: Optional[int], job_type: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Best-effort public Job Bank search scraper, enriched with application method."""
    jobs: List[Dict[str, Any]] = []
    search_url = (
        "https://www.jobbank.gc.ca/jobsearch/jobsearch"
        f"?searchstring={quote_plus(keywords)}"
        f"&locationstring={quote_plus(location or 'Canada')}"
    )

    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=_headers()) as client:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                raise ValueError(f"Job Bank returned {resp.status_code}")

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("article") or soup.select(".resultJobItem") or soup.select("[data-job-id]") or soup.select("li")

            for card in cards:
                if len(jobs) >= limit:
                    break

                title_el = card.select_one("a, h3, h2")
                if not title_el:
                    continue

                title = title_el.get_text(" ", strip=True)
                if not title or len(title) > 180:
                    continue

                href = title_el.get("href", "")
                jobbank_listing_url = _jobbank_url(href)
                if not jobbank_listing_url:
                    continue
                text = card.get_text(" ", strip=True)

                if not _looks_relevant(title, text, keywords):
                    continue

                company = "Unknown"
                location_text = location or "Canada"
                for selector in [".business", ".employer", ".company", "[class*=employer]", "[class*=business]"]:
                    found = card.select_one(selector)
                    if found and found.get_text(strip=True):
                        company = found.get_text(" ", strip=True)
                        break

                for selector in [".location", "[class*=location]", "[class*=city]"]:
                    found = card.select_one(selector)
                    if found and found.get_text(strip=True):
                        location_text = found.get_text(" ", strip=True)
                        break

                sal_lo, sal_hi = _parse_salary(text, salary_min, salary_max)
                apply_info = await resolve_application_method(jobbank_listing_url, client=client)
                method = apply_info.get("application_method", "manual")
                selected_url = apply_info.get("selected_apply_url") if method == "external_url" else jobbank_listing_url

                jobs.append({
                    "external_id": _uid("jobbank", company, title, jobbank_listing_url),
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "salary_min": sal_lo,
                    "salary_max": sal_hi,
                    "salary_currency": "CAD",
                    "job_type": job_type or "full_time",
                    "description": text[:2000],
                    "requirements": "",
                    "url": selected_url,
                    "source": "jobbank",
                    "posted_at": datetime.utcnow().isoformat(),
                    "application_method": method,
                    "raw_data": {
                        **apply_info,
                        "jobbank_original_url": jobbank_listing_url,
                        "search_url": search_url,
                    },
                })
    except Exception:
        return _fallback_or_empty(keywords, location, salary_min, salary_max, job_type, "jobbank", limit)

    return jobs


async def scrape_indeed(keywords: str, location: Optional[str], salary_min: Optional[int], salary_max: Optional[int], job_type: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Discovery-only. Indeed regularly blocks scraping and login-less auto-submit is unsafe."""
    jobs: List[Dict[str, Any]] = []
    query_params = {"q": keywords, "l": location or "", "limit": min(limit, 50), "fromage": "14"}
    if salary_min:
        query_params["salary"] = f"${salary_min}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=_headers()) as client:
            resp = await client.get("https://ca.indeed.com/jobs", params=query_params)
            if resp.status_code != 200:
                raise ValueError(f"Indeed returned {resp.status_code}")
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.job_seen_beacon") or soup.select("div[data-jk]")
            for card in cards[:limit]:
                title_el = card.select_one("h2.jobTitle span[title], h2.jobTitle a")
                company_el = card.select_one("span.companyName, [data-testid='company-name']")
                location_el = card.select_one("div.companyLocation, [data-testid='text-location']")
                salary_el = card.select_one("div.salary-snippet-container, [data-testid='attribute_snippet_testid']")
                link_el = card.select_one("h2.jobTitle a, a[data-jk]")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                loc = location_el.get_text(strip=True) if location_el else (location or "")
                salary_text = salary_el.get_text(strip=True) if salary_el else ""
                jk = card.get("data-jk") or (link_el.get("data-jk") if link_el else None)
                href = link_el.get("href", "") if link_el else ""
                job_url = f"https://ca.indeed.com/viewjob?jk={jk}" if jk else (f"https://ca.indeed.com{href}" if href.startswith("/") else href)
                sal_lo, sal_hi = _parse_salary(salary_text, salary_min, salary_max)
                jobs.append({
                    "external_id": jk or _uid("indeed", company, title, job_url),
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
                    "source": "indeed",
                    "raw_data": {"application_method": "unsupported_job_board", "reason": "Indeed listing pages are discovery-only"},
                })
    except Exception:
        return _fallback_or_empty(keywords, location, salary_min, salary_max, job_type, "indeed", limit)

    return jobs


async def scrape_linkedin(keywords: str, location: Optional[str], salary_min: Optional[int], salary_max: Optional[int], job_type: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Discovery-only. LinkedIn apply usually requires login and is not safe for headless auto-submit."""
    jobs: List[Dict[str, Any]] = []
    jt_map = {"full_time": "F", "part_time": "P", "contract": "C", "internship": "I"}
    params = {"keywords": keywords, "location": location or "Canada", "f_JT": jt_map.get(job_type or "", ""), "start": 0}

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=_headers()) as client:
            resp = await client.get("https://www.linkedin.com/jobs/search", params=params)
            if resp.status_code != 200:
                raise ValueError(f"LinkedIn returned {resp.status_code}")
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.base-search-card") or soup.select("li.jobs-search-results__list-item")
            for card in cards[:limit]:
                title_el = card.select_one("h3.base-search-card__title, h3.job-result-card__title")
                company_el = card.select_one("h4.base-search-card__subtitle, a.job-result-card__subtitle-link")
                location_el = card.select_one("span.job-search-card__location")
                link_el = card.select_one("a.base-card__full-link, a.result-card__full-card-link")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                text = card.get_text(" ", strip=True)
                if not _looks_relevant(title, text, keywords):
                    continue
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                loc = location_el.get_text(strip=True) if location_el else (location or "")
                href = link_el.get("href", "") if link_el else ""
                jobs.append({
                    "external_id": _uid("linkedin", company, title, href),
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "salary_currency": "CAD",
                    "job_type": job_type or "full_time",
                    "description": text[:2000],
                    "requirements": "",
                    "url": href,
                    "source": "linkedin",
                    "raw_data": {"application_method": "unsupported_job_board", "reason": "LinkedIn listing pages are discovery-only"},
                })
    except Exception:
        return _fallback_or_empty(keywords, location, salary_min, salary_max, job_type, "linkedin", limit)

    return jobs


async def scrape_glassdoor(keywords: str, location: Optional[str], salary_min: Optional[int], salary_max: Optional[int], job_type: Optional[str], limit: int) -> List[Dict[str, Any]]:
    # Glassdoor aggressively blocks scrapers. Do not invent jobs unless dev mocks are explicitly enabled.
    return _fallback_or_empty(keywords, location, salary_min, salary_max, job_type, "glassdoor", limit)


def _normalize_sources(sources: Optional[List[Any]]) -> List[str]:
    # Default to Job Bank only because LinkedIn/Indeed are discovery-only and cause repeated manual-review loops.
    if not sources:
        return ["jobbank"]
    normalized = []
    for source in sources:
        value = getattr(source, "value", source)
        normalized.append(str(value).lower())
    return normalized


async def search_jobs(keywords: str, location: Optional[str] = None, salary_min: Optional[int] = None, salary_max: Optional[int] = None, job_type: Optional[str] = None, sources: Optional[List[str]] = None, limit: int = 50) -> List[Dict[str, Any]]:
    normalized_sources = _normalize_sources(sources)
    per_source = max(5, min(25, limit // max(len(normalized_sources), 1) + 1))

    tasks = []
    if "jobbank" in normalized_sources:
        tasks.append(scrape_jobbank(keywords, location, salary_min, salary_max, job_type, per_source))
    if "indeed" in normalized_sources:
        tasks.append(scrape_indeed(keywords, location, salary_min, salary_max, job_type, per_source))
    if "linkedin" in normalized_sources:
        tasks.append(scrape_linkedin(keywords, location, salary_min, salary_max, job_type, per_source))
    if "glassdoor" in normalized_sources:
        tasks.append(scrape_glassdoor(keywords, location, salary_min, salary_max, job_type, per_source))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_jobs: List[Dict[str, Any]] = []
    for result in results:
        if isinstance(result, list):
            all_jobs.extend(result)

    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for job in all_jobs:
        eid = job.get("external_id") or _uid(job.get("source", "manual"), job.get("company", ""), job.get("title", ""), job.get("url", ""))
        if eid in seen:
            continue
        seen.add(eid)
        job["external_id"] = eid
        raw = dict(job.get("raw_data") or {})
        if job.get("application_method") and "application_method" not in raw:
            raw["application_method"] = job.get("application_method")
        job["raw_data"] = raw
        unique.append(job)

    def _priority(job: Dict[str, Any]) -> int:
        method = (job.get("raw_data") or {}).get("application_method")
        return {"external_url": 0, "email": 1, "manual": 2, "unsupported_job_board": 3}.get(method, 4)

    unique.sort(key=lambda job: (_priority(job), -float(job.get("salary_min") or 0)))
    return unique[:limit]
