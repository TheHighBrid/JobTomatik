"""Select current public Workday Candidate Experience jobs for certification.

The selector uses public tenant CXS listing feeds and skips unavailable tenants or
malformed records. It never uses candidate credentials or application endpoints.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin

import httpx


DEFAULT_TENANTS: List[Tuple[str, str, str]] = [
    ("workday.wd5.myworkdayjobs.com", "workday", "Workday"),
    ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite"),
    ("salesforce.wd12.myworkdayjobs.com", "salesforce", "External_Career_Site"),
    ("mastercard.wd1.myworkdayjobs.com", "mastercard", "CorporateCareers"),
    ("blackrock.wd1.myworkdayjobs.com", "blackrock", "BlackRock_Professional"),
]


def _listing_url(host: str, tenant: str, site: str) -> str:
    return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"


def _job_url(host: str, site: str, external_path: str) -> str:
    path = str(external_path or "").strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    if not path.casefold().startswith(f"/en-us/{site.casefold()}/"):
        path = f"/en-US/{site}{path}"
    return urljoin(f"https://{host}", path)


async def _tenant_candidates(
    client: httpx.AsyncClient,
    host: str,
    tenant: str,
    site: str,
    *,
    per_tenant: int,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "host": host,
        "tenant": tenant,
        "site": site,
        "listing_url": _listing_url(host, tenant, site),
        "status": "pending",
        "jobs": [],
    }
    try:
        response = await client.post(
            result["listing_url"],
            json={
                "appliedFacets": {},
                "limit": max(10, per_tenant * 4),
                "offset": 0,
                "searchText": "",
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        result["http_status"] = response.status_code
        response.raise_for_status()
        payload = response.json()
        postings = payload.get("jobPostings") if isinstance(payload, dict) else []
        if not isinstance(postings, list):
            postings = []
        for item in postings:
            if not isinstance(item, dict):
                continue
            url = _job_url(host, site, str(item.get("externalPath") or ""))
            if not url:
                continue
            result["jobs"].append({
                "url": url,
                "title": item.get("title"),
                "external_path": item.get("externalPath"),
                "locations_text": item.get("locationsText"),
                "posted_on": item.get("postedOn"),
                "bullet_fields": item.get("bulletFields") or [],
            })
            if len(result["jobs"]) >= per_tenant:
                break
        result["total"] = payload.get("total") if isinstance(payload, dict) else None
        result["status"] = "ok" if result["jobs"] else "no_jobs"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    return result


async def main_async(args) -> int:
    tenants = list(DEFAULT_TENANTS)
    if args.tenants_json:
        raw = json.loads(Path(args.tenants_json).read_text())
        tenants = [
            (str(item["host"]), str(item["tenant"]), str(item["site"]))
            for item in raw
            if isinstance(item, dict)
        ]

    async with httpx.AsyncClient(timeout=args.timeout, follow_redirects=True) as client:
        reports = []
        for host, tenant, site in tenants:
            reports.append(await _tenant_candidates(
                client,
                host,
                tenant,
                site,
                per_tenant=args.per_tenant,
            ))

    candidates = []
    for report in reports:
        for job in report.get("jobs") or []:
            candidates.append({
                **job,
                "host": report["host"],
                "tenant": report["tenant"],
                "site": report["site"],
            })
            if len(candidates) >= args.limit:
                break
        if len(candidates) >= args.limit:
            break

    summary = {
        "certification": "workday_current_candidate_selection",
        "tenant_count": len(tenants),
        "successful_tenant_count": sum(item.get("status") == "ok" for item in reports),
        "candidate_count": len(candidates),
        "reports": reports,
        "candidates": candidates,
    }
    Path(args.output).write_text(json.dumps(summary, indent=2, default=str))
    Path(args.urls_output).write_text(
        "\n".join(str(item["url"]) for item in candidates) + ("\n" if candidates else "")
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0 if candidates else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="workday-candidates.json")
    parser.add_argument("--urls-output", default="workday-candidates.txt")
    parser.add_argument("--tenants-json", default="")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--per-tenant", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
