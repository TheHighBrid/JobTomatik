"""Fail-closed evidence gates layered over Lever pilot readiness summaries.

The canonical ingestion service remains responsible for schema validation and ledger
integrity. This module independently derives certification counts from retained source
rows so incomplete evidence can never become ready merely through optimistic defaults.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from app.services.greenhouse_pilot import (
    SUCCESS_STATUSES,
    SUPERVISED_MODE,
    UNCERTAIN_STATUS,
)

PHASE_A_READY_PAIR = ("ready_to_submit", "dry_run_passed")
PHASE_A_BOUNDARY_PAIR = ("manual_challenge_handoff", "needs_review")
PHASE_A_REQUIRED_RECORDS = 30
PHASE_B_REQUIRED_RECORDS = 10
VALID_REGIONS = {"global", "eu"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _phase_a_rows(path: Optional[str | Path]) -> list[Dict[str, str]]:
    if path is None or not Path(path).is_file():
        return []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _phase_b_rows(path: Optional[str | Path]) -> list[Dict[str, Any]]:
    if path is None or not Path(path).is_file():
        return []
    rows: list[Dict[str, Any]] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if raw.strip():
            value = json.loads(raw)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _record_keys(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for name in (
        "run_id",
        "approval_reference",
        "confirmation_evidence_reference",
        "external_application_id",
    ):
        value = str(record.get(name) or "").strip().lower()
        if value:
            values.append((name, value))
    site = str(record.get("site") or record.get("board_token") or "").strip().lower()
    posting_id = str(
        record.get("posting_id") or record.get("job_id") or ""
    ).strip().lower()
    region = str(record.get("region") or "").strip().lower()
    if site and posting_id and region:
        values.append(("target_identity", f"{region}:{site}:{posting_id}"))
    return values


def _duplicate_indexes(records: Iterable[Mapping[str, Any]]) -> set[int]:
    rows = list(records)
    counts = Counter(key for record in rows for key in _record_keys(record))
    return {
        index
        for index, record in enumerate(rows)
        if record.get("duplicate_submission_detected") is True
        or any(counts[key] > 1 for key in _record_keys(record))
    }


def record_hash_mismatch(record: Mapping[str, Any]) -> bool:
    return record.get("evidence_payload_hash") != record.get("combined_payload_hash")


def harden_lever_readiness(
    readiness: Mapping[str, Any],
    *,
    baseline_path: Optional[str | Path],
    ledger_path: Optional[str | Path],
) -> Dict[str, Any]:
    """Recompute readiness from explicit evidence gates and fail closed on omissions."""

    payload = dict(readiness)
    summary = dict(payload.get("summary") or {})
    gates = dict(summary.get("gates") or {})

    phase_a = _phase_a_rows(baseline_path)
    qualifying = [
        row
        for row in phase_a
        if (
            str(row.get("pre_submit_state") or "").strip(),
            str(row.get("final_status") or "").strip(),
        )
        == PHASE_A_READY_PAIR
        and _truthy(row.get("official_posting_inspection_passed"))
    ]
    boundary_only = [
        row
        for row in phase_a
        if (
            str(row.get("pre_submit_state") or "").strip(),
            str(row.get("final_status") or "").strip(),
        )
        == PHASE_A_BOUNDARY_PAIR
    ]
    inspection_failures = [
        row
        for row in phase_a
        if not _truthy(row.get("official_posting_inspection_passed"))
    ]
    sites = {
        str(row.get("site") or "").strip().lower()
        for row in qualifying
        if str(row.get("site") or "").strip()
    }
    regions = {
        str(row.get("region") or "").strip().lower()
        for row in qualifying
        if str(row.get("region") or "").strip()
    }

    phase_b = [
        row for row in _phase_b_rows(ledger_path) if row.get("mode") == SUPERVISED_MODE
    ]
    raw_successes = [
        row for row in phase_b if row.get("final_status") in SUCCESS_STATUSES
    ]
    duplicate_indexes = _duplicate_indexes(raw_successes)
    false_submitted = [
        row
        for row in raw_successes
        if not str(row.get("confirmation_evidence_reference") or "").strip()
    ]
    unreviewed = [
        row
        for row in raw_successes
        if not str(row.get("reviewed_by") or "").strip()
        or not str(row.get("review_reference") or "").strip()
    ]
    hash_mismatches = [
        row
        for row in raw_successes
        if not str(row.get("evidence_payload_hash") or "").strip()
        or record_hash_mismatch(row)
    ]
    uncertain_violations = [
        row
        for row in phase_b
        if row.get("pre_submit_state") == UNCERTAIN_STATUS
        and row.get("final_status") != UNCERTAIN_STATUS
    ]
    safe_successes = [
        row
        for index, row in enumerate(raw_successes)
        if index not in duplicate_indexes
        and row not in false_submitted
        and row not in unreviewed
        and row not in hash_mismatches
        and row not in uncertain_violations
    ]

    gates.update(
        {
            "thirty_qualifying_dry_runs": len(qualifying)
            >= PHASE_A_REQUIRED_RECORDS,
            "thirty_distinct_lever_sites": len(sites) >= PHASE_A_REQUIRED_RECORDS,
            "global_and_eu_hosts_covered": VALID_REGIONS.issubset(regions),
            "all_phase_a_records_have_successful_matching_inspection": not inspection_failures,
            "ten_supervised_confirmed_submissions": len(safe_successes)
            >= PHASE_B_REQUIRED_RECORDS,
            "zero_false_submitted_records": not false_submitted,
            "zero_duplicate_submissions": not duplicate_indexes,
            "all_uncertain_outcomes_remain_uncertain": not uncertain_violations,
            "all_success_evidence_independently_reviewed": bool(raw_successes)
            and not unreviewed,
            "all_evidence_hashes_match_consumed_approvals": not hash_mismatches,
            "explicit_separate_promotion_approval": False,
        }
    )

    summary.update(
        {
            "qualifying_dry_run_count": len(qualifying),
            "nonqualifying_dry_run_count": len(phase_a) - len(qualifying),
            "manual_challenge_boundary_count": len(boundary_only),
            "phase_a_inspection_failure_count": len(inspection_failures),
            "distinct_site_count": len(sites),
            "regions_covered": sorted(regions),
            "raw_supervised_confirmed_count": len(raw_successes),
            "supervised_confirmed_count": len(safe_successes),
            "false_submitted_count": len(false_submitted),
            "duplicate_submission_count": len(duplicate_indexes),
            "uncertain_status_violation_count": len(uncertain_violations),
            "unreviewed_success_count": len(unreviewed),
            "payload_hash_mismatch_count": len(hash_mismatches),
            "gates": gates,
        }
    )
    required = [
        value
        for key, value in gates.items()
        if key != "explicit_separate_promotion_approval"
    ]
    summary["supervised_pilot_evidence_complete"] = all(required)
    summary["promotion_ready"] = all(gates.values())
    payload["summary"] = summary
    payload["readiness_hardening_version"] = "1.0"
    return payload


__all__ = ["harden_lever_readiness"]
