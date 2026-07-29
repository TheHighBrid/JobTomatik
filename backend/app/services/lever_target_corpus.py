"""Locked Lever Phase A target-corpus validation and reporting.

The corpus is a reviewed planning input, not submission evidence. This module validates
that Day 8 reviewed enough live official Lever postings, selected enough distinct sites,
and preserved exact target identity without contacting any posting or submitting data.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from app.services.ats_lever import (
    LEVER_EU_JOBS_HOST,
    LEVER_GLOBAL_JOBS_HOST,
    parse_lever_job_url,
)

MIN_ACTIVE_REVIEWED_POSTINGS = 40
MIN_VIABLE_DISTINCT_SITES = 30
VALID_REGIONS = {"global", "eu"}
GENERIC_ROLE_MARKERS = (
    "general application",
    "general interest",
    "spontaneous application",
    "keep in touch",
)
REQUIRED_COLUMNS = (
    "review_id",
    "employer",
    "role",
    "site",
    "posting_id",
    "region",
    "posting_url",
    "canonical_application_url",
    "location",
    "work_type",
    "reviewed_at_utc",
    "verification_method",
    "observed_http_status",
    "apply_link_present",
    "lever_powered_present",
    "active",
    "viable",
    "exclusion_reason",
    "review_digest_sha256",
)


class LeverTargetCorpusError(ValueError):
    """Raised when the locked target corpus violates the Day 8 contract."""


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _canonical_review_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in REQUIRED_COLUMNS:
        if field == "review_digest_sha256":
            continue
        value: Any = row.get(field, "")
        if field in {"apply_link_present", "lever_powerered_present", "active", "viable"}:
            value = _truthy(value)
        else:
            value = str(value or "").strip()
        payload[field] = value
    return payload


def review_digest(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _canonical_review_payload(row),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _corpus_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        files = sorted(path.glob("part-*.csv"))
        if files:
            return files
    raise LeverTargetCorpusError(f"Lever target corpus not found: {path}")


def load_target_corpus(path: str | Path) -> list[dict[str, str]]:
    corpus_path = Path(path)
    rows: list[dict[str, str]] = []
    for part in _corpus_files(corpus_path):
        with part.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
                raise LeverTargetCorpusError(
                    f"Lever target corpus columns do not match the locked schema: {part}"
                )
            rows.extend(dict(row) for row in reader)
    if not rows:
        raise LeverTargetCorpusError("Lever target corpus cannot be empty")
    return rows


def corpus_digest(path: str | Path) -> str:
    corpus_path = Path(path)
    digest = hashlib.sha256()
    for part in _corpus_files(corpus_path):
        digest.update(part.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(part.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _expected_urls(site: str, posting_id: str, region: str) -> tuple[str, str]:
    host = LEVER_EU_JOBS_HOST if region == "eu" else LEVER_GLOBAL_JOBS_HOST
    posting = f"https://{host}/{site}/{posting_id}"
    return posting, f"{posting}/apply"


def _validate_target_identity(row: Mapping[str, Any]) -> None:
    site = str(row.get("site") or "").strip()
    posting_id = str(row.get("posting_id") or "").strip()
    region = str(row.get("region") or "").strip().lower()
    posting_url = str(row.get("posting_url") or "").strip()
    application_url = str(row.get("canonical_application_url") or "").strip()

    if not site or not posting_id or region not in VALID_REGIONS:
        raise LeverTargetCorpusError("Every corpus row requires site, posting_id, and valid region")

    expected_posting, expected_application = _expected_urls(site, posting_id, region)
    if posting_url.rstrip("/") != expected_posting:
        raise LeverTargetCorpusError(f"Posting URL does not match target identity: {row.get('review_id')}")
    if application_url.rstrip("/") != expected_application:
        raise LeverTargetCorpusError(
            f"Canonical application URL does not match target identity: {row.get('review_id')}"
        )

    parsed = urlparse(posting_url)
    expected_host = LEVER_EU_JOBS_HOST if region == "eu" else LEVER_GLOBAL_JOBS_HOST
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != expected_host
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise LeverTargetCorpusError(f"Posting URL is not canonical HTTPS: {row.get('review_id')}")

    observed_site, observed_posting_id, observed_region = parse_lever_job_url(application_url)
    if (observed_site, observed_posting_id, observed_region) != (site, posting_id, region):
        raise LeverTargetCorpusError(f"Parsed target identity mismatch: {row.get('review_id')}")


def validate_target_corpus(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [
        _canonical_review_payload(row)
        | {
            "review_digest_sha256": str(row.get("review_digest_sha256") or "")
            .strip()
            .lower()
        }
        for row in rows
    ]
    review_ids: set[str] = set()
    target_ids: set[tuple[str, str, str]] = set()
    viable_sites: set[str] = set()

    for row in normalized:
        review_id = row["review_id"]
        if not review_id or review_id in review_ids:
            raise LeverTargetCorpusError(f"Duplicate or missing review_id: {review_id or '<empty>'}")
        review_ids.add(review_id)

        for required in ("employer", "role", "site", "posting_id", "reviewed_at_utc"):
            if not row[required]:
                raise LeverTargetCorpusError(f"{review_id} is missing {required}")
        if row["verification_method"] != "official_page_open":
            raise LeverTargetCorpusError(f"{review_id} must use official_page_open verification")

        _validate_target_identity(row)
        target_id = (row["region"], row["site"].lower(), row["posting_id"].lower())
        if target_id in target_ids:
            raise LeverTargetCorpusError(f"Duplicate posting target: {review_id}")
        target_ids.add(target_id)

        expected_digest = review_digest(row)
        if row["review_digest_sha256"] != expected_digest:
            raise LeverTargetCorpusError(f"Review digest mismatch: {review_id}")

        active = bool(row["active"])
        viable = bool(row["viable"])
        if active:
            if row["observed_http_status"] != "200":
                raise LeverTargetCorpusError(f"Active row lacks HTTP 200 verification: {review_id}")
            if not row["apply_link_present"] or not row["lever_powered_present"]:
                raise LeverTargetCorpusError(f"Active row lacks official Lever page signals: {review_id}")
        elif viable:
            raise LeverTargetCorpusError(f"Inactive row cannot be viable: {review_id}")

        role_lower = row["role"].lower()
        generic_role = any(marker in role_lower for marker in GENERIC_ROLE_MARKERS)
        if viable:
            site_key = row["site"].lower()
            if site_key in viable_sites:
                raise LeverTargetCorpusError(f"Duplicate viable site: {review_id}")
            viable_sites.add(site_key)
            if generic_role:
                raise LeverTargetCorpusError(f"Generic application cannot enter viable corpus: {review_id}")
            if row["exclusion_reason"]:
                raise LeverTargetCorpusError(f"Viable row cannot carry an exclusion reason: {review_id}")
        elif not row["exclusion_reason"]:
            raise LeverTargetCorpusError(f"Excluded row requires an explicit reason: {review_id}")

    return normalized


def certify_target_corpus(path: str | Path) -> dict[str, Any]:
    raw_rows = load_target_corpus(path)
    rows = validate_target_corpus(raw_rows)
    active = [row for row in rows if row["active"]]
    viable = [row for row in rows if row["viable"]]
    viable_sites = {row["site"].lower() for row in viable}
    regions = {row["region"] for row in viable}
    region_counts = Counter(row["region"] for row in viable)

    gates = {
        "at_least_40_active_official_postings_reviewed": len(active) >= MIN_ACTIVE_REVIEWED_POSTINGS,
        "at_least_30_viable_distinct_sites_locked": len(viable_sites) >= MIN_VIABLE_DISTINCT_SITES,
        "global_and_eu_hosts_covered": VALID_REGIONS.issubset(regions),
        "zero_duplicate_viable_sites": len(viable_sites) == len(viable),
        "all_viable_rows_are_active": all(row["active"] for row in viable),
        "all_viable_rows_have_official_page_signals": all(
            row["apply_link_present"] and row["lever_powered_present"] for row in viable
        ),
    }
    corpus_path = Path(path)
    return {
        "schema_version": "1.0",
        "corpus_path": corpus_path.as_posix(),
        "corpus_sha256": corpus_digest(corpus_path),
        "summary": {
            "reviewed_posting_count": len(rows),
            "active_reviewed_posting_count": len(active),
            "viable_posting_count": len(viable),
            "distinct_viable_site_count": len(viable_sites),
            "excluded_posting_count": len(rows) - len(viable),
            "regions_covered": sorted(regions),
            "viable_region_counts": dict(sorted(region_counts.items())),
            "gates": gates,
            "passed": all(gates.values()),
        },
        "viable_targets": [
            {
                "review_id": row["review_id"],
                "site": row["site"],
                "posting_id": row["posting_id"],
                "region": row["region"],
                "role": row["role"],
                "canonical_application_url": row["canonical_application_url"],
                "review_digest_sha256": row["review_digest_sha256"],
            }
            for row in viable
        ],
        "excluded_targets": [
            {
                "review_id": row["review_id"],
                "site": row["site"],
                "posting_id": row["posting_id"],
                "region": row["region"],
                "role": row["role"],
                "observed_http_status": row["observed_http_status"],
                "exclusion_reason": row["exclusion_reason"],
            }
            for row in rows
            if not row["viable"]
        ],
        "safety": {
            "network_contacted_by_certifier": False,
            "browser_opened_by_certifier": False,
            "application_data_entered": False,
            "final_submit_clicked": False,
            "approval_issued": False,
            "maturity_promoted": False,
        },
    }


def render_target_corpus_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    gates = summary["gates"]
    lines = [
        "# Lever Phase A Target Corpus Certification",
        "",
        f"- Result: **{'PASS' if summary['passed'] else 'FAIL'}**",
        f"- Reviewed postings: **{summary['reviewed_posting_count']}**",
        f"- Active official postings: **{summary['active_reviewed_posting_count']}**",
        f"- Viable locked postings: **{summary['viable_posting_count']}**",
        f"- Distinct viable sites: **{summary['distinct_viable_site_count']}**",
        f"- Regions: **{', '.join(summary['regions_covered'])}**",
        f"- Corpus SHA-256: `{report['corpus_sha256']}`",
        "",
        "## Gates",
        "",
    ]
    lines.extend(f"- [{'x' if passed else ' '}] `{name}`" for name, passed in gates.items())
    lines.extend(["", "## Exclusions", ""])
    for item in report["excluded_targets"]:
        lines.append(
            f"- `{item['review_id']}` `{item['region']}:{item['site']}:{item['posting_id']}`: "
            f"{item['exclusion_reason']}"
        )
    lines.extend(
        [
            "",
            "The certifier performs no network access, enters no applicant data, and cannot submit or promote an adapter.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "LeverTargetCorpusError",
    "certify_target_corpus",
    "corpus_digest",
    "load_target_corpus",
    "render_target_corpus_markdown",
    "review_digest",
    "validate_target_corpus",
]
