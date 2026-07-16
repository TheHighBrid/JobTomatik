"""Evidence ledger and readiness reporting for the Greenhouse supervised pilot.

This module does not submit applications. It normalizes retained certification
reports, rejects any dry-run report that clicked final submit, deduplicates run
records, and computes conservative promotion readiness for roadmap issue #13.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


DRY_RUN_MODE = "dry_run"
SUPERVISED_MODE = "supervised_real_submission"
QUALIFYING_DRY_RUN_OUTCOMES = {"ready_to_submit", "manual_challenge_handoff"}
SUCCESS_STATUSES = {"submitted", "confirmed"}
UNCERTAIN_STATUS = "submission_uncertain"


class PilotEvidenceError(ValueError):
    """Raised when retained pilot evidence violates a safety invariant."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stable_run_id(source_reference: str, index: int, report: Mapping[str, Any]) -> str:
    payload = {
        "source_reference": source_reference,
        "index": index,
        "url": report.get("url"),
        "mode": report.get("mode"),
        "adapter": report.get("adapter"),
        "adapter_version": report.get("adapter_version"),
        "certification_metadata": report.get("certification_metadata") or {},
    }
    return "gh-" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:20]


def _first_handoff(review_items: Sequence[Mapping[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    for item in review_items:
        reason = str(item.get("reason_code") or "").strip()
        if not reason:
            continue
        details = item.get("details") if isinstance(item.get("details"), Mapping) else {}
        boundary = str(details.get("handoff_stage") or details.get("boundary") or "").strip()
        return reason, boundary or None
    return None, None


def _verified_upload_count(upload_evidence: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for item in upload_evidence if item.get("verification") == "passed")


def _qualifies_as_dry_run(report: Mapping[str, Any]) -> bool:
    return bool(
        report.get("mode") == "exercise"
        and report.get("passed") is True
        and report.get("adapter") == "greenhouse"
        and report.get("certification_outcome") in QUALIFYING_DRY_RUN_OUTCOMES
        and report.get("final_submit_clicked") is False
    )


def normalize_dry_run_report(
    summary: Mapping[str, Any],
    *,
    operator: str,
    source_reference: str,
    completed_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convert one retained Greenhouse certification report into ledger records.

    Inspection-only entries remain visible in the source report but do not count as
    representative dry runs. Only successful ``exercise`` entries are normalized.
    Any evidence of a final submit click fails closed and rejects the whole report.
    """

    if not operator.strip():
        raise PilotEvidenceError("operator is required")
    if not source_reference.strip():
        raise PilotEvidenceError("source_reference is required")
    if summary.get("final_submit_clicked") is not False:
        raise PilotEvidenceError("dry-run summary must explicitly record final_submit_clicked=false")

    reports = summary.get("reports")
    if not isinstance(reports, list):
        raise PilotEvidenceError("certification report must contain a reports list")

    normalized: List[Dict[str, Any]] = []
    timestamp = completed_at or _now_iso()
    for index, item in enumerate(reports):
        if not isinstance(item, Mapping) or item.get("mode") != "exercise":
            continue
        if item.get("final_submit_clicked") is not False:
            raise PilotEvidenceError(
                f"exercise report {index} does not explicitly record final_submit_clicked=false"
            )

        metadata = item.get("certification_metadata")
        if not isinstance(metadata, Mapping):
            metadata = {}
        review_items = item.get("review_items")
        if not isinstance(review_items, list):
            review_items = []
        upload_evidence = item.get("upload_evidence")
        if not isinstance(upload_evidence, list):
            upload_evidence = []
        validation_errors = item.get("validation_errors")
        if not isinstance(validation_errors, list):
            validation_errors = []

        handoff_reason, handoff_boundary = _first_handoff(review_items)
        outcome = str(item.get("certification_outcome") or "failed")
        qualifies = _qualifies_as_dry_run(item)
        final_status = (
            "dry_run_passed"
            if qualifies and outcome == "ready_to_submit"
            else "needs_review"
            if qualifies and outcome == "manual_challenge_handoff"
            else "failed"
        )
        controls_observed = int(item.get("control_evidence_count") or 0)
        fields_filled = int(item.get("fields_filled") or 0)

        normalized.append(
            {
                "schema_version": "1.0",
                "run_id": _stable_run_id(source_reference, index, item),
                "mode": DRY_RUN_MODE,
                "started_at": None,
                "completed_at": timestamp,
                "employer": str(metadata.get("company_name") or "").strip() or None,
                "role": str(metadata.get("job_title") or "").strip() or None,
                "board_token": str(metadata.get("board_token") or "").strip() or None,
                "job_id": str(metadata.get("job_id") or "").strip() or None,
                "application_url": item.get("url"),
                "adapter": item.get("adapter"),
                "adapter_version": item.get("adapter_version"),
                "framework_version": summary.get("framework_version"),
                "operator": operator.strip(),
                "source_reference": source_reference.strip(),
                "approval_reference": None,
                "profile_snapshot_hash": None,
                "resume_hash": None,
                "cover_letter_hash": None,
                "answer_payload_hash": None,
                "controls_discovered": max(controls_observed, fields_filled),
                "controls_filled": fields_filled,
                "controls_skipped": None,
                "controls_blocked": len(review_items),
                "policies_used": int(metadata.get("policy_count") or 0),
                "uploads_verified": _verified_upload_count(upload_evidence),
                "validation_errors": validation_errors,
                "handoff_reason": handoff_reason,
                "handoff_boundary": handoff_boundary,
                "pre_submit_state": outcome,
                "final_url": item.get("final_url") or item.get("url"),
                "final_submit_clicked": False,
                "confirmation_evidence_type": None,
                "confirmation_evidence_reference": None,
                "final_status": final_status,
                "duplicate_guard_verified": None,
                "duplicate_submission_detected": False,
                "reviewed_by": None,
                "review_reference": None,
                "qualifies_for_dry_run_matrix": qualifies,
                "synthetic_profile": bool(metadata.get("synthetic_profile")),
                "error": item.get("error"),
                "notes": None,
            }
        )
    return normalized


def validate_record(record: Mapping[str, Any]) -> None:
    mode = record.get("mode")
    if mode not in {DRY_RUN_MODE, SUPERVISED_MODE}:
        raise PilotEvidenceError(f"unsupported pilot mode: {mode!r}")
    if not str(record.get("run_id") or "").strip():
        raise PilotEvidenceError("run_id is required")
    if mode == DRY_RUN_MODE and record.get("final_submit_clicked") is not False:
        raise PilotEvidenceError("dry-run records must explicitly record final_submit_clicked=false")

    status = record.get("final_status")
    evidence = str(record.get("confirmation_evidence_reference") or "").strip()
    if status in SUCCESS_STATUSES and not evidence:
        raise PilotEvidenceError("successful submission records require confirmation evidence")
    if mode == SUPERVISED_MODE and record.get("final_submit_clicked") is True:
        if not str(record.get("approval_reference") or "").strip():
            raise PilotEvidenceError("supervised final-submit evidence requires approval_reference")


def load_ledger(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PilotEvidenceError(f"invalid JSONL at line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise PilotEvidenceError(f"ledger line {line_number} must be a JSON object")
        validate_record(value)
        records.append(value)
    return records


def merge_records(
    existing: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for source in (existing, incoming):
        for raw in source:
            record = dict(raw)
            validate_record(record)
            run_id = str(record["run_id"])
            if run_id in merged:
                if _canonical_json(merged[run_id]) != _canonical_json(record):
                    raise PilotEvidenceError(f"conflicting evidence for run_id {run_id}")
                continue
            merged[run_id] = record
            order.append(run_id)
    return [merged[run_id] for run_id in order]


def write_ledger(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    values = [dict(record) for record in records]
    for record in values:
        validate_record(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(_canonical_json(record) + "\n" for record in values)
    path.write_text(payload, encoding="utf-8")


def build_readiness_summary(
    records: Iterable[Mapping[str, Any]],
    *,
    release_approval_reference: Optional[str] = None,
) -> Dict[str, Any]:
    values = [dict(record) for record in records]
    for record in values:
        validate_record(record)

    qualifying_dry = [
        record
        for record in values
        if record.get("mode") == DRY_RUN_MODE
        and record.get("qualifies_for_dry_run_matrix") is True
    ]
    dry_employers = {
        str(record.get("employer") or "").strip().lower()
        for record in qualifying_dry
        if str(record.get("employer") or "").strip()
    }
    supervised = [record for record in values if record.get("mode") == SUPERVISED_MODE]
    supervised_success = [
        record for record in supervised if record.get("final_status") in SUCCESS_STATUSES
    ]
    false_submitted = [
        record
        for record in supervised_success
        if not str(record.get("confirmation_evidence_reference") or "").strip()
    ]
    duplicate_submissions = [
        record for record in supervised if record.get("duplicate_submission_detected") is True
    ]
    uncertain_violations = [
        record
        for record in supervised
        if record.get("pre_submit_state") == UNCERTAIN_STATUS
        and record.get("final_status") != UNCERTAIN_STATUS
    ]
    unreviewed_success = [
        record
        for record in supervised_success
        if not str(record.get("reviewed_by") or "").strip()
        or not str(record.get("review_reference") or "").strip()
    ]

    gates = {
        "thirty_qualifying_dry_runs": len(qualifying_dry) >= 30,
        "thirty_distinct_employers": len(dry_employers) >= 30,
        "ten_supervised_confirmed_submissions": len(supervised_success) >= 10,
        "zero_false_submitted_records": not false_submitted,
        "zero_duplicate_submissions": not duplicate_submissions,
        "all_uncertain_outcomes_remain_uncertain": not uncertain_violations,
        "all_success_evidence_independently_reviewed": bool(supervised_success)
        and not unreviewed_success,
        "explicit_release_approval_reference": bool(
            str(release_approval_reference or "").strip()
        ),
    }
    return {
        "schema_version": "1.0",
        "generated_at": _now_iso(),
        "record_count": len(values),
        "qualifying_dry_run_count": len(qualifying_dry),
        "distinct_dry_run_employer_count": len(dry_employers),
        "supervised_record_count": len(supervised),
        "supervised_confirmed_count": len(supervised_success),
        "false_submitted_count": len(false_submitted),
        "duplicate_submission_count": len(duplicate_submissions),
        "uncertain_status_violation_count": len(uncertain_violations),
        "unreviewed_success_count": len(unreviewed_success),
        "release_approval_reference": release_approval_reference,
        "gates": gates,
        "human_reviewed_submit_ready": all(gates.values()),
    }


def render_readiness_markdown(summary: Mapping[str, Any]) -> str:
    gates = summary.get("gates") if isinstance(summary.get("gates"), Mapping) else {}
    lines = [
        "# Greenhouse Supervised Pilot Readiness",
        "",
        f"Generated: `{summary.get('generated_at')}`",
        "",
        "## Progress",
        "",
        f"- Qualifying dry runs: **{summary.get('qualifying_dry_run_count', 0)} / 30**",
        f"- Distinct dry-run employers: **{summary.get('distinct_dry_run_employer_count', 0)} / 30**",
        f"- Confirmed supervised submissions: **{summary.get('supervised_confirmed_count', 0)} / 10**",
        f"- Total retained records: **{summary.get('record_count', 0)}**",
        "",
        "## Release gates",
        "",
        "| Gate | Status |",
        "|---|---|",
    ]
    for name, passed in gates.items():
        label = name.replace("_", " ").capitalize()
        lines.append(f"| {label} | {'PASS' if passed else 'BLOCKED'} |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "`human_reviewed_submit` promotion is **READY**."
            if summary.get("human_reviewed_submit_ready")
            else "`human_reviewed_submit` promotion remains **BLOCKED**.",
            "",
            "This report never authorizes `certified_autonomous` maturity.",
            "",
        ]
    )
    return "\n".join(lines)
