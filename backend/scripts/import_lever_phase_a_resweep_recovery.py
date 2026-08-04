#!/usr/bin/env python3
"""Run the Lever Phase A resweep importer with corrected supersession mapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.lever_pilot_ingestion import load_phase_a_baseline
from scripts import import_lever_phase_a_resweep as importer


def _target_identity(row: dict[str, Any]) -> str:
    region = str(row.get("region") or "").strip().casefold()
    posting_id = str(row.get("posting_id") or "").strip().casefold()
    return f"{region}:lever:{posting_id}"


def _assert_initial_state(
    baseline_path: Path,
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    fields, raw_rows = importer._read_rows(baseline_path)
    typed_rows = load_phase_a_baseline(baseline_path)
    if len(raw_rows) != 3 or len(typed_rows) != 3:
        raise AssertionError((len(raw_rows), len(typed_rows)))
    if sum(row.get("qualifies_for_dry_run_matrix") is True for row in typed_rows) != 1:
        raise AssertionError("Expected one qualifying row before the resweep import")

    typed_matches = [
        row
        for row in typed_rows
        if row.get("target_identity") == importer.SUPERSEDED_TARGET
        and row.get("run_id") == importer.SUPERSEDED_RUN_ID
        and row.get("final_status") == "needs_review"
        and row.get("handoff_reason") == "captcha_detected"
        and row.get("valid_manual_challenge_handoff") is True
        and row.get("final_submit_clicked") is False
    ]
    if len(typed_matches) != 1:
        raise AssertionError(("superseded typed row", typed_matches))

    raw_matches = [
        row
        for row in raw_rows
        if row.get("run_id") == importer.SUPERSEDED_RUN_ID
        and _target_identity(row) == importer.SUPERSEDED_TARGET
        and row.get("final_status") == "needs_review"
        and row.get("handoff_reason") == "captcha_detected"
        and row.get("pre_submit_state") == "manual_challenge_handoff"
    ]
    if len(raw_matches) != 1:
        raise AssertionError(("superseded raw row", raw_matches))
    return fields, raw_rows, raw_matches[0]


def _write_supersession(
    evidence: Path,
    superseded: dict[str, str],
    imported_rows: list[dict[str, str]],
) -> dict[str, Any]:
    expected_path = (
        "lever-phase-a-artifacts/"
        + importer.SUPERSEDING_REVIEW_ID
        + "/lever-phase-a-report.json"
    )
    superseding = [
        row for row in imported_rows if row.get("artifact_path") == expected_path
    ]
    if len(superseding) != 1:
        raise AssertionError(superseding)
    superseding_row = superseding[0]
    if _target_identity(superseding_row) != importer.SUPERSEDED_TARGET:
        raise AssertionError(superseding_row)

    receipt = {
        "schema_version": "1.0",
        "target_identity": importer.SUPERSEDED_TARGET,
        "reason": "stronger_exact_target_ready_evidence",
        "superseded": superseded,
        "superseding": {
            "review_id": importer.SUPERSEDING_REVIEW_ID,
            "run_id": superseding_row["run_id"],
            "artifact_path": superseding_row["artifact_path"],
            "artifact_sha256": superseding_row["artifact_sha256"],
            "source_reference": superseding_row["source_reference"],
            "pre_submit_state": superseding_row["pre_submit_state"],
            "final_status": superseding_row["final_status"],
            "final_submit_clicked": False,
        },
        "safety": {
            "historical_boundary_preserved": True,
            "final_submit_clicked": False,
            "quota_credit_counted_once": True,
        },
    }
    (evidence / "lever-phase-a-supersessions.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    # Keep raw CSV checks separate from derived ingestion fields.
    # The merge bridge is locked to this same-repository PR head.
    importer._assert_initial_state = _assert_initial_state
    importer._write_supersession = _write_supersession
    importer.main()


if __name__ == "__main__":
    main()
