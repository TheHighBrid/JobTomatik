#!/usr/bin/env python3
"""Build exact, read-only Lever Phase B launch dossiers from retained Phase A evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SELECTION_SCHEMA_VERSION = "1.0"
LAUNCH_SCHEMA_VERSION = "1.1"
DOSSIER_SNAPSHOT_VERSION = "1.2.0"
DOSSIER_SCOPE = "lever_supervised_phase_b_candidate"
SELECTION_POLICY = "user_selected_exact_application_no_ranking"


class LeverPhaseBLaunchError(RuntimeError):
    """Raised when Day 15 evidence cannot be built safely."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_baseline(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _single(items: list[Mapping[str, Any]], label: str) -> Mapping[str, Any]:
    if len(items) != 1:
        raise LeverPhaseBLaunchError(f"Expected exactly one {label}; found {len(items)}")
    return items[0]


def _bool_text(value: Any) -> bool:
    return str(value or "").strip().casefold() == "true"


def _validate_selection(selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    if selection.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise LeverPhaseBLaunchError("Unsupported selection receipt schema")
    if selection.get("selected_by_user") is not True:
        raise LeverPhaseBLaunchError("Selection receipt is not explicitly user-selected")
    if not str(selection.get("selection_quote") or "").strip():
        raise LeverPhaseBLaunchError("Selection receipt is missing the exact user quote")

    requested = selection.get("requested_action")
    if not isinstance(requested, Mapping):
        raise LeverPhaseBLaunchError("Selection receipt is missing requested_action")
    if requested.get("build_read_only_dossiers") is not True:
        raise LeverPhaseBLaunchError("Read-only dossier creation was not selected")
    if requested.get("run_no_submit_previews") is not True:
        raise LeverPhaseBLaunchError("No-submit previews were not selected")
    for forbidden in (
        "authorize_final_submit",
        "authorize_supervised_submission",
        "authorize_adapter_promotion",
    ):
        if requested.get(forbidden) is not False:
            raise LeverPhaseBLaunchError(f"{forbidden} must remain false")

    safety = selection.get("safety")
    if not isinstance(safety, Mapping):
        raise LeverPhaseBLaunchError("Selection receipt is missing safety controls")
    for required in (
        "one_time_approval_still_required",
        "final_submit_must_remain_false",
        "no_captcha_bypass",
        "no_sensitive_or_legal_answer_inference",
    ):
        if safety.get(required) is not True:
            raise LeverPhaseBLaunchError(
                f"Selection safety control is not true: {required}"
            )

    raw = selection.get("selected_applications")
    applications = [dict(item) for item in raw or [] if isinstance(item, Mapping)]
    if len(applications) != 2 or len(raw or []) != 2:
        raise LeverPhaseBLaunchError("Day 15 requires exactly two selected applications")
    review_ids = [str(item.get("review_id") or "").strip() for item in applications]
    posting_ids = [str(item.get("posting_id") or "").strip() for item in applications]
    if any(not value for value in review_ids + posting_ids):
        raise LeverPhaseBLaunchError(
            "Selected applications require review_id and posting_id"
        )
    if len(set(review_ids)) != 2 or len(set(posting_ids)) != 2:
        raise LeverPhaseBLaunchError("Selected applications must be distinct")
    return applications


def _baseline_row(
    rows: list[dict[str, str]], selection: Mapping[str, Any]
) -> dict[str, str]:
    review_id = str(selection["review_id"])
    expected_path = f"lever-phase-a-artifacts/{review_id}/lever-phase-a-report.json"
    matches = [row for row in rows if row.get("artifact_path") == expected_path]
    row = dict(_single(matches, f"baseline row for {review_id}"))

    exact_fields = {
        "employer": selection.get("employer"),
        "role": selection.get("role"),
        "site": selection.get("site"),
        "posting_id": selection.get("posting_id"),
        "application_url": selection.get("application_url"),
    }
    for field, expected in exact_fields.items():
        if str(row.get(field) or "") != str(expected or ""):
            raise LeverPhaseBLaunchError(
                f"{review_id} baseline {field} does not match the user selection"
            )
    if not _bool_text(row.get("official_posting_inspection_passed")):
        raise LeverPhaseBLaunchError(
            f"{review_id} lacks a successful official inspection"
        )
    if row.get("pre_submit_state") != "ready_to_submit":
        raise LeverPhaseBLaunchError(f"{review_id} is not retained as ready_to_submit")
    if row.get("final_status") != "dry_run_passed":
        raise LeverPhaseBLaunchError(f"{review_id} is not a qualifying dry run")
    if not row.get("artifact_sha256"):
        raise LeverPhaseBLaunchError(f"{review_id} baseline is missing artifact_sha256")
    return row


def _validate_report(
    report_path: Path,
    report_sha256: str,
    row: Mapping[str, str],
    selection: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    report_bytes = report_path.read_bytes()
    if _sha256_bytes(report_bytes) != report_sha256:
        raise LeverPhaseBLaunchError(
            f"{selection['review_id']} report hash does not match the canonical baseline"
        )
    report = json.loads(report_bytes)
    if not isinstance(report, Mapping):
        raise LeverPhaseBLaunchError("Phase A report must be a JSON object")
    if report.get("final_submit_clicked") is not False:
        raise LeverPhaseBLaunchError("Phase A report indicates a final submit click")
    if report.get("passed") is not True:
        raise LeverPhaseBLaunchError("Phase A report did not pass")

    items = [item for item in report.get("reports") or [] if isinstance(item, Mapping)]
    inspect = _single(
        [item for item in items if item.get("mode") == "inspect"], "inspection"
    )
    exercise = _single(
        [item for item in items if item.get("mode") == "exercise"], "exercise"
    )

    if inspect.get("passed") is not True or inspect.get("posting_available") is not True:
        raise LeverPhaseBLaunchError("Official posting inspection did not pass")
    if inspect.get("final_submit_clicked") is not False:
        raise LeverPhaseBLaunchError("Inspection indicates a final submit click")
    posting = inspect.get("posting_metadata")
    if (
        not isinstance(posting, Mapping)
        or posting.get("posting_metadata_certified") is not True
    ):
        raise LeverPhaseBLaunchError("Official posting metadata is not certified")

    expected_posting = {
        "posting_id": selection.get("posting_id"),
        "title": selection.get("role"),
        "site": selection.get("site"),
        "apply_url": selection.get("application_url"),
        "region": row.get("region"),
    }
    for field, expected in expected_posting.items():
        if str(posting.get(field) or "") != str(expected or ""):
            raise LeverPhaseBLaunchError(
                f"{selection['review_id']} official posting {field} mismatch"
            )

    if exercise.get("passed") is not True:
        raise LeverPhaseBLaunchError("No-submit preview did not pass")
    if exercise.get("certification_outcome") != "ready_to_submit":
        raise LeverPhaseBLaunchError("No-submit preview is not ready_to_submit")
    if exercise.get("ready_to_submit") is not True:
        raise LeverPhaseBLaunchError("No-submit preview is not marked ready")
    if exercise.get("requires_manual_review") is not False:
        raise LeverPhaseBLaunchError("No-submit preview still requires manual review")
    if exercise.get("final_submit_clicked") is not False:
        raise LeverPhaseBLaunchError("No-submit preview indicates a final submit click")
    if exercise.get("review_items") not in (None, []):
        raise LeverPhaseBLaunchError("No-submit preview contains unresolved review items")
    if exercise.get("validation_errors") not in (None, []):
        raise LeverPhaseBLaunchError("No-submit preview contains validation errors")

    metadata = exercise.get("certification_metadata")
    if not isinstance(metadata, Mapping):
        raise LeverPhaseBLaunchError("No-submit preview lacks certification metadata")
    for field in ("site", "posting_id", "region"):
        if str(metadata.get(field) or "") != str(row.get(field) or ""):
            raise LeverPhaseBLaunchError(
                f"{selection['review_id']} preview metadata {field} mismatch"
            )
    if metadata.get("synthetic_profile") is not True:
        raise LeverPhaseBLaunchError("Day 15 preview must remain synthetic")

    return inspect, exercise


def _build_dossier(
    *,
    selection: Mapping[str, Any],
    selection_path: str,
    selection_sha256: str,
    selection_receipt: Mapping[str, Any],
    row: Mapping[str, str],
    report_path: str,
    report_sha256: str,
    inspect: Mapping[str, Any],
) -> dict[str, Any]:
    review_id = str(selection["review_id"])
    site = str(selection["site"])
    posting_id = str(selection["posting_id"])
    application_id = f"lever:{site.casefold()}:{posting_id}"
    posting = dict(inspect["posting_metadata"])
    categories = posting.get("categories")
    location = ""
    if isinstance(categories, Mapping):
        location = str(categories.get("location") or "")

    dossier: dict[str, Any] = {
        "application_id": application_id,
        "dry_preview": {
            "final_submit_clicked": False,
            "outcome": "ready_to_submit",
            "passed": True,
            "ready_to_submit": True,
            "requires_manual_review": False,
            "retained_phase_a_preview": True,
            "source_report_path": report_path,
            "source_report_sha256": report_sha256,
        },
        "kill_switches": {
            "adapter_promotion_allowed": False,
            "final_submit_allowed": False,
            "one_time_approval_required": True,
            "supervised_submission_allowed": False,
        },
        "read_only": True,
        "scope": DOSSIER_SCOPE,
        "selection_policy": SELECTION_POLICY,
        "selection_receipt": {
            "path": selection_path,
            "receipt_id": selection_receipt.get("receipt_id"),
            "recorded_at": selection_receipt.get("recorded_at"),
            "review_id": review_id,
            "sha256": selection_sha256,
        },
        "snapshot_version": DOSSIER_SNAPSHOT_VERSION,
        "source_phase_a": {
            "adapter_version": row.get("adapter_version"),
            "artifact_path": report_path,
            "artifact_sha256": report_sha256,
            "baseline_run_id": row.get("run_id"),
            "completed_at": row.get("completed_at"),
            "controls_discovered": int(row.get("controls_discovered") or 0),
            "controls_filled": int(row.get("controls_filled") or 0),
            "final_status": row.get("final_status"),
            "official_posting_inspection_passed": True,
            "pre_submit_state": row.get("pre_submit_state"),
            "review_id": review_id,
            "source_reference": row.get("source_reference"),
            "synthetic_profile": True,
        },
        "target": {
            "application_url": selection.get("application_url"),
            "employer": selection.get("employer"),
            "location": location,
            "platform": "lever",
            "posting_id": posting_id,
            "region": row.get("region"),
            "role": selection.get("role"),
            "site": site,
        },
    }
    dossier_sha256 = _canonical_sha256(dossier)
    filename = f"lever-phase-b-dossier-{review_id}.json"
    dossier["dossier_sha256"] = dossier_sha256
    dossier["download_filename"] = filename
    return dossier


def build_launch(
    *,
    evidence_root: Path,
    selection_path: Path,
    baseline_path: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    evidence_root = evidence_root.resolve()
    selection_path = selection_path.resolve()
    baseline_path = baseline_path.resolve()
    selection_bytes = selection_path.read_bytes()
    selection_sha256 = _sha256_bytes(selection_bytes)
    selection_receipt = json.loads(selection_bytes)
    if not isinstance(selection_receipt, Mapping):
        raise LeverPhaseBLaunchError("Selection receipt must be a JSON object")
    selected = _validate_selection(selection_receipt)
    baseline = _load_baseline(baseline_path)

    dossiers: dict[str, bytes] = {}
    applications: list[dict[str, Any]] = []
    selection_relative = selection_path.relative_to(evidence_root).as_posix()

    for selected_application in selected:
        row = _baseline_row(baseline, selected_application)
        report_relative = str(row["artifact_path"])
        report_path = (evidence_root / report_relative).resolve()
        try:
            report_path.relative_to(evidence_root)
        except ValueError as exc:
            raise LeverPhaseBLaunchError(
                "Phase A report path escapes evidence root"
            ) from exc
        inspect, _exercise = _validate_report(
            report_path,
            str(row["artifact_sha256"]),
            row,
            selected_application,
        )
        dossier = _build_dossier(
            selection=selected_application,
            selection_path=selection_relative,
            selection_sha256=selection_sha256,
            selection_receipt=selection_receipt,
            row=row,
            report_path=report_relative,
            report_sha256=str(row["artifact_sha256"]),
            inspect=inspect,
        )
        dossier_bytes = _json_bytes(dossier)
        filename = str(dossier["download_filename"])
        dossier_relative = f"lever-phase-b-dossiers/{filename}"
        dossiers[dossier_relative] = dossier_bytes

        applications.append(
            {
                "application_id": dossier["application_id"],
                "dossier": {
                    "artifact_path": dossier_relative,
                    "artifact_sha256": _sha256_bytes(dossier_bytes),
                    "dossier_sha256": dossier["dossier_sha256"],
                    "one_time_approval_required": True,
                    "read_only": True,
                },
                "dry_preview": dict(dossier["dry_preview"]),
                "platform": "lever",
                "selected_by_user": True,
                "selection_reference": (
                    f"{selection_relative}#{selected_application['review_id']}"
                ),
                "selection_receipt_sha256": selection_sha256,
                "target": dict(dossier["target"]),
            }
        )

    launch = {
        "applications": applications,
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "selection_receipt": {
            "path": selection_relative,
            "receipt_id": selection_receipt.get("receipt_id"),
            "sha256": selection_sha256,
        },
    }
    return launch, dossiers


def _write_or_check(path: Path, expected: bytes, check: bool) -> None:
    if check:
        if not path.is_file():
            raise LeverPhaseBLaunchError(f"Missing generated artifact: {path}")
        if path.read_bytes() != expected:
            raise LeverPhaseBLaunchError(f"Generated artifact drift: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", default="evidence")
    parser.add_argument(
        "--selection",
        default="evidence/lever-phase-b-user-selection-2026-08-04.json",
    )
    parser.add_argument("--baseline", default="evidence/lever-phase-a-baseline.csv")
    parser.add_argument(
        "--launch-output", default="evidence/lever-phase-b-launch.json"
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    evidence_root = Path(args.evidence_root)
    launch, dossiers = build_launch(
        evidence_root=evidence_root,
        selection_path=Path(args.selection),
        baseline_path=Path(args.baseline),
    )
    for relative, payload in dossiers.items():
        _write_or_check(evidence_root / relative, payload, args.check)
    _write_or_check(Path(args.launch_output), _json_bytes(launch), args.check)

    print(
        json.dumps(
            {
                "application_count": len(launch["applications"]),
                "application_ids": [
                    item["application_id"] for item in launch["applications"]
                ],
                "check_only": args.check,
                "final_submit_clicked": False,
                "one_time_approval_required": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
