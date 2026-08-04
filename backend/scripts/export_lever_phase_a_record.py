#!/usr/bin/env python3
"""Export one immutable Lever Phase A candidate row from a dry-run report.

This tool never appends to the canonical baseline. It emits a single CSV candidate
that an operator can review alongside the retained report artifact and digest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.services.ats_lever import LEVER_ADAPTER_VERSION, parse_lever_job_url
from app.services.lever_pilot_ingestion import load_phase_a_baseline


FIELDNAMES = [
    "run_id",
    "completed_at",
    "employer",
    "role",
    "site",
    "posting_id",
    "region",
    "application_url",
    "adapter_version",
    "operator",
    "source_reference",
    "artifact_sha256",
    "artifact_path",
    "official_posting_inspection_passed",
    "controls_discovered",
    "controls_filled",
    "controls_skipped",
    "controls_blocked",
    "policies_used",
    "uploads_verified",
    "handoff_reason",
    "handoff_boundary",
    "pre_submit_state",
    "final_status",
    "error",
    "notes",
]


class LeverPhaseAExportError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy_evidence_count(exercise: Mapping[str, Any]) -> int:
    evidence = exercise.get("control_evidence")
    if isinstance(evidence, list):
        return sum(
            1
            for item in evidence
            if isinstance(item, Mapping) and item.get("source") != "profile"
        )
    if exercise.get("policy_evidence_count") is not None:
        return int(exercise.get("policy_evidence_count") or 0)
    return int(exercise.get("control_evidence_count") or 0)


def _default_artifact_path(report_path: Path, output_path: Path) -> str:
    """Return a verifier-safe report path relative to the exported CSV.

    Canonical candidates resolve retained artifacts from the CSV's parent directory.
    Preserve report subdirectories instead of collapsing the reference to a basename.
    """

    report = report_path.resolve()
    output_root = output_path.resolve().parent
    try:
        relative = report.relative_to(output_root)
    except ValueError as exc:
        raise LeverPhaseAExportError(
            "When --artifact-path is omitted, --report must be retained beneath the "
            "output CSV directory so the candidate can reference it safely"
        ) from exc
    if not relative.parts or relative == Path("."):
        raise LeverPhaseAExportError("The retained report artifact path is invalid")
    return relative.as_posix()


def _matching_inspection(report: Mapping[str, Any], url: str) -> Mapping[str, Any]:
    inspections = [
        item
        for item in report.get("reports") or []
        if item.get("mode") == "inspect"
        and str(item.get("url") or "").rstrip("/") == url.rstrip("/")
    ]
    if len(inspections) != 1:
        raise LeverPhaseAExportError(
            "Exactly one matching official-posting inspection is required"
        )
    inspection = inspections[0]
    if inspection.get("passed") is not True:
        raise LeverPhaseAExportError(
            "The matching official-posting inspection did not pass"
        )
    if inspection.get("adapter") != "lever":
        raise LeverPhaseAExportError("The matching inspection must use the Lever adapter")
    if str(inspection.get("adapter_version") or "") != LEVER_ADAPTER_VERSION:
        raise LeverPhaseAExportError(
            f"The matching inspection must use Lever adapter {LEVER_ADAPTER_VERSION}"
        )
    if inspection.get("final_submit_clicked") is not False:
        raise LeverPhaseAExportError(
            "The matching inspection must record final_submit_clicked=false"
        )
    return inspection


def _matching_exercise(report: Mapping[str, Any]) -> Mapping[str, Any]:
    exercises = [item for item in report.get("reports") or [] if item.get("mode") == "exercise"]
    if len(exercises) != 1:
        raise LeverPhaseAExportError("Exactly one Lever exercise report is required")
    exercise = exercises[0]
    if exercise.get("passed") is not True:
        raise LeverPhaseAExportError("The Lever dry-run exercise did not pass")
    if exercise.get("final_submit_clicked") is not False:
        raise LeverPhaseAExportError("Phase A evidence must record final_submit_clicked=false")
    if exercise.get("adapter") != "lever":
        raise LeverPhaseAExportError("Phase A evidence must use the Lever adapter")
    if str(exercise.get("adapter_version") or "") != LEVER_ADAPTER_VERSION:
        raise LeverPhaseAExportError(
            f"Phase A evidence must use Lever adapter {LEVER_ADAPTER_VERSION}"
        )
    return exercise


def build_phase_a_candidate(
    report: Mapping[str, Any],
    *,
    report_path: Path,
    run_id: str,
    operator: str,
    source_reference: str,
    employer: str,
    role: str,
    completed_at: Optional[str] = None,
    artifact_path: Optional[str] = None,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if report.get("final_submit_clicked") is not False:
        raise LeverPhaseAExportError("The certification summary must record final_submit_clicked=false")
    exercise = _matching_exercise(report)
    url = str(exercise.get("url") or "").strip()
    site, posting_id, region = parse_lever_job_url(url)
    if not site or not posting_id or region not in {"global", "eu"}:
        raise LeverPhaseAExportError("The exercise URL is not an exact global or EU Lever target")

    inspection = _matching_inspection(report, url)
    outcome = str(exercise.get("certification_outcome") or "").strip()
    if outcome == "ready_to_submit":
        final_status = "dry_run_passed"
    elif outcome == "manual_challenge_handoff":
        final_status = "needs_review"
    else:
        raise LeverPhaseAExportError("The exercise outcome is not retained Phase A evidence")

    review_items = list(exercise.get("review_items") or [])
    challenge_codes = {
        "captcha_detected",
        "mfa_required",
        "login_required",
        "anti_bot_challenge",
    }
    handoff = next(
        (
            item
            for item in review_items
            if item.get("reason_code") in challenge_codes
        ),
        None,
    )
    upload_evidence = list(exercise.get("upload_evidence") or [])
    verified_uploads = sum(1 for item in upload_evidence if item.get("verification") == "passed")
    validation_errors = list(exercise.get("validation_errors") or [])
    blocking_review_items = [
        item for item in review_items if item.get("reason_code") not in challenge_codes
    ]
    dom = dict(inspection.get("dom") or {})
    controls_discovered = int(dom.get("visible_control_count") or 0)
    controls_filled = int(exercise.get("fields_filled") or 0)
    controls_blocked = len(validation_errors) + len(blocking_review_items)
    controls_skipped = max(0, controls_discovered - controls_filled - controls_blocked)
    timestamp = completed_at or datetime.now(timezone.utc).isoformat()

    required_text = {
        "run_id": run_id,
        "operator": operator,
        "source_reference": source_reference,
        "employer": employer,
        "role": role,
    }
    missing = [name for name, value in required_text.items() if not str(value or "").strip()]
    if missing:
        raise LeverPhaseAExportError("Missing required export values: " + ", ".join(missing))

    if artifact_path is not None:
        artifact_reference = str(artifact_path).strip()
    elif output_path is not None:
        artifact_reference = _default_artifact_path(report_path, output_path)
    else:
        artifact_reference = report_path.name

    return {
        "run_id": str(run_id).strip(),
        "completed_at": timestamp,
        "employer": str(employer).strip(),
        "role": str(role).strip(),
        "site": site,
        "posting_id": posting_id,
        "region": region,
        "application_url": url,
        "adapter_version": LEVER_ADAPTER_VERSION,
        "operator": str(operator).strip(),
        "source_reference": str(source_reference).strip(),
        "artifact_sha256": _sha256(report_path),
        "artifact_path": artifact_reference,
        "official_posting_inspection_passed": True,
        "controls_discovered": controls_discovered,
        "controls_filled": controls_filled,
        "controls_skipped": controls_skipped,
        "controls_blocked": controls_blocked,
        "policies_used": _policy_evidence_count(exercise),
        "uploads_verified": verified_uploads,
        "handoff_reason": handoff.get("reason_code") if handoff else "",
        "handoff_boundary": (handoff.get("details") or {}).get("handoff_stage") if handoff else "",
        "pre_submit_state": outcome,
        "final_status": final_status,
        "error": str(exercise.get("error") or ""),
        "notes": (
            "Synthetic ready-to-submit dry run; canonical baseline requires separate review."
            if outcome == "ready_to_submit"
            else "Synthetic manual-challenge boundary coverage; does not advance the Phase A gate."
        ),
    }


def export_phase_a_candidate(output_path: Path, record: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow({name: record.get(name, "") for name in FIELDNAMES})
    loaded = load_phase_a_baseline(output_path)
    if len(loaded) != 1:
        raise LeverPhaseAExportError("Exported Phase A candidate failed canonical validation")
    pair = (record.get("pre_submit_state"), record.get("final_status"))
    if pair not in {
        ("ready_to_submit", "dry_run_passed"),
        ("manual_challenge_handoff", "needs_review"),
    }:
        raise LeverPhaseAExportError("Exported Phase A candidate has an invalid outcome pair")
    if record.get("official_posting_inspection_passed") is not True:
        raise LeverPhaseAExportError("Exported Phase A candidate lacks a successful inspection")
    if pair == ("ready_to_submit", "dry_run_passed") and (
        loaded[0].get("qualifies_for_dry_run_matrix") is not True
    ):
        raise LeverPhaseAExportError(
            "Exported Phase A candidate is not backed by a verified retained artifact"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", default="lever-phase-a-record.csv")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--employer", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--completed-at")
    parser.add_argument("--artifact-path")
    args = parser.parse_args()

    report_path = Path(args.report)
    output_path = Path(args.output)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    record = build_phase_a_candidate(
        report,
        report_path=report_path,
        run_id=args.run_id,
        operator=args.operator,
        source_reference=args.source_reference,
        employer=args.employer,
        role=args.role,
        completed_at=args.completed_at,
        artifact_path=args.artifact_path,
        output_path=output_path,
    )
    export_phase_a_candidate(output_path, record)
    print(f"Exported Phase A candidate to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
