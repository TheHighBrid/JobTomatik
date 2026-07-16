"""Select current SmartRecruiters applications from multiple public tenants.

The selector uses only the unauthenticated official Posting API. Invalid tenant
identifiers, empty boards, inactive jobs, and missing apply URLs are skipped. It
never opens an application form or performs an application action.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import httpx


DEFAULT_COMPANIES = (
    "Visa",
    "NielsenIQ",
    "SGS",
    "BoschGroup",
    "Wolt",
    "AveryDennison",
    "TurnerTownsend",
    "Eurofins",
    "AECOM",
    "Devoteam",
    "VusionGroup",
    "PublicisGroupe",
    "H&MGroup",
    "SIXT",
    "Continental",
    "RedBull",
    "Ubisoft",
    "InterIKEAGroup",
    "smartrecruiters",
)

PREFERRED_TERMS = (
    "operations",
    "consultant",
    "support",
    "sales",
    "data",
    "analyst",
    "manager",
    "engineer",
)


def _ordered_jobs(jobs: Iterable[Dict[str, Any]], prefer_roles: bool) -> List[Dict[str, Any]]:
    records = [item for item in jobs if isinstance(item, dict)]
    records.sort(key=lambda item: str(item.get("releasedDate") or ""), reverse=True)
    if not prefer_roles:
        return records
    preferred = [
        item
        for item in records
        if any(term in str(item.get("name") or "").lower() for term in PREFERRED_TERMS)
    ]
    return preferred + [item for item in records if item not in preferred]


def select_candidates(
    companies: Iterable[str],
    *,
    limit: int,
    per_company: int,
    prefer_roles: bool,
) -> Dict[str, Any]:
    selected: List[Dict[str, Any]] = []
    tenant_reports: List[Dict[str, Any]] = []

    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for company in companies:
            company = company.strip()
            if not company or len(selected) >= limit:
                continue
            tenant: Dict[str, Any] = {
                "company_identifier": company,
                "listing_status": "pending",
                "candidate_count": 0,
            }
            try:
                listing = client.get(
                    f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                    params={"limit": 100, "offset": 0},
                )
                tenant["listing_http_status"] = listing.status_code
                if listing.status_code != 200:
                    tenant["listing_status"] = "unavailable"
                    tenant_reports.append(tenant)
                    continue
                payload = listing.json()
                jobs = _ordered_jobs(payload.get("content") or [], prefer_roles)
                tenant["listing_status"] = "available"
                tenant["reported_total"] = payload.get("totalFound")
            except Exception as exc:
                tenant["listing_status"] = "error"
                tenant["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                tenant_reports.append(tenant)
                continue

            accepted_for_company = 0
            for summary in jobs:
                if len(selected) >= limit or accepted_for_company >= per_company:
                    break
                identifier = str(summary.get("id") or summary.get("uuid") or "")
                if not identifier:
                    continue
                try:
                    details_response = client.get(
                        f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{identifier}"
                    )
                    if details_response.status_code != 200:
                        continue
                    details = details_response.json()
                except Exception:
                    continue
                apply_url = str(details.get("applyUrl") or "").strip()
                if details.get("active") is not True or not apply_url:
                    continue
                selected.append({
                    "company_identifier": company,
                    "posting_id": details.get("id"),
                    "posting_uuid": details.get("uuid"),
                    "title": details.get("name"),
                    "released_date": details.get("releasedDate"),
                    "apply_url": apply_url,
                })
                accepted_for_company += 1

            tenant["candidate_count"] = accepted_for_company
            tenant_reports.append(tenant)

    return {
        "selected_count": len(selected),
        "requested_limit": limit,
        "per_company": per_company,
        "companies": list(companies),
        "candidates": selected,
        "tenant_reports": tenant_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--urls-output", required=True)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--per-company", type=int, default=2)
    parser.add_argument("--prefer-roles", action="store_true")
    parser.add_argument("--companies", default=",")
    args = parser.parse_args()

    supplied = [value.strip() for value in args.companies.split(",") if value.strip()]
    companies = supplied or list(DEFAULT_COMPANIES)
    report = select_candidates(
        companies,
        limit=max(1, args.limit),
        per_company=max(1, args.per_company),
        prefer_roles=bool(args.prefer_roles),
    )
    if not report["candidates"]:
        raise SystemExit("No current SmartRecruiters application URLs were returned.")

    Path(args.output).write_text(json.dumps(report, indent=2, default=str))
    Path(args.urls_output).write_text(
        "\n".join(item["apply_url"] for item in report["candidates"])
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
