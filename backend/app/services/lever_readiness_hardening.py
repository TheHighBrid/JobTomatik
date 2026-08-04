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
from app.services.lever_phase_a_archive import verify_phase_a_external_archive
from app.services.lever_phase_a_evidence import verify_phase_a_row_evidence

PHASE_A_READY_PAIR = ("ready_to_submit", "dry_run_passed")
PHASE_A_BOUNDARY_PAIR = ("manual_challenge_handoff", "needs_review")
MANUAL_CHALLENGE_REASON_CODES = frozenset(
    {"captcha_detected", "mfa_required", "login_required", "anti_bot_challenge"}
)
PHASE_A_REQUIRED_RECORDS = 30
PHASE_B_REQUIRED_RECORDS = 10
VALID_REGIONS = {"global", "eu"}
SUPERSESSION_FILENAME = "lever-phase-a-supersessions.json"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _phase_a_rows(path: Optional[str | Path]) -> list[Dict[str, Any]]:
    if path is None or not Path(path).is_file():
        return []
    rows: list[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row: Dict[str, Any] = dict(raw)
            verification = verify_phase_a_row_evidence(row, baseline_path=path)
            archive = verify_phase_a_external_archive(row, baseline_path=path)
            row["_artifact_verified"] = verification["artifact_verified"]
            row["_qualification_evidence_verified"] = verification["qualifies"]
            row["_external_archive_verified"] = archive["verified"]
            row["_external_archive_path"] = archive["archive_path"]
            row["_external_archive_errors"] = list(archive["errors"])
            rows.append(row)
    return rows


def _superseded_phase_a_rows(path: Optional[str | Path]) -> list[Dict[str, Any]]:
    """Load preserved challenge attempts without restoring their quota credit."""

    if path is None:
        return []
    supersession_path = Path(path).with_name(SUPERSESSION_FILENAME)
    if not supersession_path.is_file():
        return []

    try:
        payload = json.loads(supersession_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid Lever Phase A supersession receipt: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Lever Phase A supersession receipt must be a JSON object")

    safety = payload.get("safety")
    superseded = payload.get("superseded")
    row = superseded.get("baseline_row") if isinstance(superseded, dict) else None
    if not isinstance(safety, dict) or not isinstance(row, dict):
        raise ValueError("Lever Phase A supersession receipt is missing safety or baseline evidence")
    required_safety = (
        "historical_attempt_preserved",
        "historical_source_receipt_preserved",
        "quota_credit_counted_once",
    )
    if any(safety.get(field) is not True for field in required_safety):
        raise ValueError("Lever Phase A supersession receipt does not preserve the historical boundary")
    if safety.get("final_submit_clicked") is not False:
        raise ValueError("Lever Phase A supersession receipt recorded a final submit click")

    pair = (
        str(row.get("pre_submit_state") or "").strip(),
        str(row.get("final_status") or "").strip(),
    )
    reason = str(row.get("handoff_reason") or "").strip()
    if pair != PHASE_A_BOUNDARY_PAIR or reason not in MANUAL_CHALLENGE_REASON_CODES:
        raise ValueError("Superseded Lever evidence must remain a manual challenge needs-review boundary")

    preserved = dict(row)
    preserved["_historical_supersession"] = True
    return [preserved]


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
    historical_phase_a = _superseded_phase_a_rows(baseline_path)
    phase_a_candidates = [
        row
        for row in phase_a
        if (
            str(row.get("pre_submit_state") or "").strip(),
            str(row.get("final_status") or "").strip(),
        )
        == PHASE_A_READY_PAIR
    ]
    qualifying = [
        row
        for row in phase_a_candidates
        if row.get("_qualification_evidence_verified") is True
        and row.get("_external_archive_verified") is True
    ]
    challenge_rows = [
        row
        for row in [*phase_a, *historical_phase_a]
        if str(row.get("handoff_reason") or "").strip()
        in MANUAL_CHALLENGE_REASON_CODES
        or str(row.get("pre_submit_state") or "").strip()
        == PHASE_A_BOUNDARY_PAIR[0]
    ]
    boundary_only = [
        row
        for row in challenge_rows
        if (
            str(row.get("pre_submit_state") or "").strip(),
            str(row.get("final_status") or "").strip(),
        )
        == PHASE_A_BOUNDARY_PAIR
    ]
    challenge_violations = [row for row in challenge_rows if row not in boundary_only]
    inspection_failures = [
        row
        for row in phase_a_candidates
        if row.get("_qualification_evidence_verified") is not True
    ]
    external_archive_failures = [
        row
        for row in phase_a_candidates
        if row.get("_external_archive_verified") is not True
    ]
    artifact_failures = [
        row
        for row in phase_a_candidates
        if row.get("_artifact_verified") is not True
        or row.get("_external_archive_verified") is not True
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
    duplicate_indexes = _duplicate_indexes(phase_b)
    duplicate_record_ids = {id(phase_b[index]) for index in duplicate_indexes}
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
        for row in raw_successes
        if id(row) not in duplicate_record_ids
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
            "all_qualifying_phase_a_records_have_durable_external_archives": not external_archive_failures,
            "all_manual_challenges_remain_needs_review": not challenge_violations,
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
            "historical_superseded_challenge_count": len(historical_phase_a),
            "manual_challenge_encounter_count": len(challenge_rows),
            "manual_challenge_boundary_count": len(boundary_only),
            "manual_challenge_violation_count": len(challenge_violations),
            "phase_a_inspection_failure_count": len(inspection_failures),
            "phase_a_artifact_verification_failure_count": len(artifact_failures),
            "phase_a_external_archive_failure_count": len(external_archive_failures),
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
    payload["readiness_hardening_version"] = "1.4"
    return payload


__all__ = ["harden_lever_readiness"]
