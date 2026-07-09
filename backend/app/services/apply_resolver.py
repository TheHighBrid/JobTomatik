"""
Application method resolver.

The app must not try to type into listing/search pages. This resolver turns a
Job Bank/listing page into one of three explicit lanes:
- external_url: browser form filling may run on the selected ATS/company URL
- email: email application can be prepared/sent by the email lane
- manual: no safe automation target was found
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

ATS_HINTS = (
    "workdayjobs.com",
    "myworkdayjobs.com",
    "greenhouse.io",
    "lever.co",
    "taleo.net",
    "successfactors",
    "smartrecruiters.com",
    "icims.com",
    "dayforcehcm.com",
    "bamboohr.com",
    "ashbyhq.com",
    "jobvite.com",
    "ultipro.com",
    "adp.com",
    "oraclecloud.com",
    "recruitee.com",
    "applytojob.com",
    "clearcompany.com",
    "paycomonline.net",
    "breezy.hr",
    "isolvedhire.com",
)

APPLY_WORDS = (
    "apply",
    "application",
    "career",
    "careers",
    "job",
    "jobs",
    "recruit",
    "postuler",
    "emploi",
    "candidature",
)

UNSUPPORTED_JOB_BOARDS = (
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
)

SKIP_DOMAINS = (
    "jobbank.gc.ca",
    "canada.ca",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "google.com",
)


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8,fr;q=0.7",
    }


def _domain(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower()
    except Exception:
        return ""


def _is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url or "")
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def is_unsupported_job_board_url(url: str) -> bool:
    host = _domain(url)
    return any(host == board or host.endswith("." + board) for board in UNSUPPORTED_JOB_BOARDS)


def is_external_candidate(url: str) -> bool:
    if not _is_http_url(url):
        return False
    host = _domain(url)
    if any(skip in host for skip in SKIP_DOMAINS):
        return False
    return True


def is_probably_ats_or_company_apply_url(url: str) -> bool:
    hay = (url or "").lower()
    if any(hint in hay for hint in ATS_HINTS):
        return True
    return any(word in hay for word in APPLY_WORDS) and not is_unsupported_job_board_url(url)


def score_apply_link(url: str, label: str) -> int:
    hay = f"{url} {label}".lower()
    score = 0
    if any(hint in hay for hint in ATS_HINTS):
        score += 100
    if any(word in hay for word in APPLY_WORDS):
        score += 45
    if "mailto:" in hay:
        score -= 100
    if any(bad in hay for bad in ("privacy", "terms", "cookie", "facebook", "linkedin", "instagram")):
        score -= 80
    return score


def extract_application_method_from_html(page_url: str, html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    page_text = soup.get_text(" ", strip=True)
    emails = sorted(set(EMAIL_RE.findall(page_text)))

    links: List[Dict[str, Any]] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        label = a.get_text(" ", strip=True)

        if href.lower().startswith("mailto:"):
            email = href.split(":", 1)[1].split("?", 1)[0].strip()
            if EMAIL_RE.match(email):
                emails.append(email)
            continue

        absolute = urljoin(page_url, href)
        if not is_external_candidate(absolute):
            continue
        score = score_apply_link(absolute, label)
        links.append({"url": absolute, "text": label, "score": score})

    emails = sorted(set(e for e in emails if not e.lower().startswith(("noreply@", "no-reply@"))))
    links = sorted(links, key=lambda item: item["score"], reverse=True)
    good_links = [item for item in links if item["score"] >= 40]

    base: Dict[str, Any] = {
        "jobbank_original_url": page_url,
        "apply_email_candidates": emails[:10],
        "apply_url_candidates": good_links[:5],
        "external_link_candidates": links[:10],
    }

    if good_links:
        best = good_links[0]["url"]
        return {
            **base,
            "application_method": "external_url",
            "selected_apply_url": best,
            "reason": "Found external application/careers URL",
        }

    if emails:
        return {
            **base,
            "application_method": "email",
            "selected_apply_email": emails[0],
            "reason": "Found application email",
        }

    return {
        **base,
        "application_method": "manual",
        "reason": "No external application URL or email found",
    }


async def resolve_application_method(job_url: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    if not _is_http_url(job_url):
        return {"application_method": "manual", "reason": "Invalid URL", "jobbank_original_url": job_url}

    if is_unsupported_job_board_url(job_url):
        return {
            "application_method": "unsupported_job_board",
            "reason": "LinkedIn/Indeed/Glassdoor listing pages are not safe auto-submit targets",
            "jobbank_original_url": job_url,
        }

    if is_probably_ats_or_company_apply_url(job_url) and "jobbank.gc.ca" not in _domain(job_url):
        return {
            "application_method": "external_url",
            "selected_apply_url": job_url,
            "reason": "URL already looks like an ATS/company application page",
        }

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=25, follow_redirects=True, headers=_headers())
        close_client = True

    try:
        response = await client.get(job_url, headers=_headers())
        response.raise_for_status()
        return extract_application_method_from_html(str(response.url), response.text)
    except Exception as exc:
        return {
            "application_method": "manual",
            "reason": f"Could not resolve application method: {str(exc)[:200]}",
            "jobbank_original_url": job_url,
        }
    finally:
        if close_client:
            await client.aclose()
