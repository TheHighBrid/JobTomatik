#!/usr/bin/env python3
"""Verify the committed Lever Phase A checkpoint and durable provenance."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from app.services.lever_day14_supersession import (
    verify_day14_supersession_ledger,
)
from app.services.lever_phase_a_archive import verify_phase_a_external_archive
from app.services.lever_pilot_ingestion import (
    load_phase_a_baseline,
    render_readiness_markdown,
)
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness

_ACTIONS_RUN = re.compile(
    r"https://github\.com/TheHighBrid/JobTomatik/actions/runs/([1-9][0-9]*)"
)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DIGITS = re.compile(r"[1-9][0-9]*")
_MIN_QUALIFYING_DRY_RUNS = 30
_TARGET_QUALIFYING_DRY_RUNS = 30
_EXPECTED_STALE_SOURCE = {
    "workflow_run_id": "30337038142",
    "artifact_id": "8679562746",
    "artifact_digest": (
        "c72bf99c62394393ef98100f3c5deee2b6bdcaa839d163bd0d9dc03a60d711e2"
    ),
    "retained_record_count": "1",
}


def _require(condition: bool, message: Any) -> None:
    if not condition:
        raise AssertionError(message)


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError((path, type(value).__name__))
    return value


def _verify_supersession(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    _require(value["schema_version"] == "1.0", "unexpected_schema_version")
    _require(
        value["reason"] == "stronger_exact_target_ready_evidence",
        "unexpected_supersession_reason",
    )
    _require(
        value["target"]
        == {
            "region": "eu",
            "site": "lever",
            "posting_id": "065f4538-7347-4207-909f-4ea68f63b4af",
        },
        "unexpected_supersession_target",
    )

    superseded = value["superseded"]
    _require(
        superseded["run_id"] == "github-actions-30337038142-1",
        "unexpected_superseded_run_id",
    )
    _require(
        superseded["pre_submit_state"] == "manual_challenge_handoff",
        "unexpected_superseded_pre_submit_state",
    )
    _require(
        superseded["final_status"] == "needs_review",
        "unexpected_superseded_final_status",
    )
    _require(
        superseded["handoff_reason"] == "captcha_detected",
        "unexpected_superseded_handoff_reason",
    )
    _require(
        superseded["source_reference"].endswith("/30337038142"),
        "unexpected_superseded_source_reference",
    )
    _require(superseded["region"] == "eu", "unexpected_superseded_region")
    _require(superseded["site"] == "lever", "unexpected_superseded_site")
    _require(
        superseded["posting_id"] == "065f4538-7347-4207-909f-4ea68f63b4af",
        "unexpected_superseded_posting_id",
    )

    superseding = value["superseding"]
    _require(
        superseding["run_id"] == "github-actions-30871406281-ready-d8-043",
        "unexpected_superseding_run_id",
    )
    _require(
        superseding["artifact_path"]
        == "lever-phase-a-artifacts/D8-043/lever-phase-a-report.json",
        "unexpected_superseding_artifact_path",
    )
    _require(
        superseding["pre_submit_state"] == "ready_to_submit",
        "unexpected_superseding_pre_submit_state",
    )
    _require(
        superseding["final_status"] == "dry_run_passed",
        "unexpected_superseding_final_status",
    )
    _require(
        superseding["source_reference"].endswith("/30871406281"),
        "unexpected_superseding_source_reference",
    )

    _require(
        value["safety"]
        == {
            "final_submit_clicked": False,
            "historical_boundary_preserved": True,
            "quota_credit_counted_once": True,
        },
        "unexpected_supersession_safety_contract",
    )
    return value


def verify_checkpoint(
    *,
    evidence_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    baseline_path = evidence_root / "lever-phase-a-baseline.csv"
    sources_path = evidence_root / "lever-phase-a-sources.csv"
    readiness_json_path = evidence_root / "lever-pilot-readiness.json"
    readiness_markdown_path = evidence_root / "lever-pilot-readiness.md"
    supersession_path = evidence_root / "lever-phase-a-supersessions.json"
    day14_supersession_path = (
        evidence_root / "lever-phase-a-day14-supersessions.json"
    )
    missing_runtime_ledger = output_root / "missing-phase-b.jsonl"

    output_root.mkdir(parents=True, exist_ok=True)
    records = load_phase_a_baseline(baseline_path)
    qualifying_records = [
        record
        for record in records
        if record["qualifies_for_dry_run_matrix"] is True
    ]
    nonqualifying_records = [
        record
        for record in records
        if record["qualifies_for_dry_run_matrix"] is not True
    ]
    qualifying_count = len(qualifying_records)

    _require(
        _MIN_QUALIFYING_DRY_RUNS <= qualifying_count <= _TARGET_QUALIFYING_DRY_RUNS,
        ("qualifying_count", qualifying_count),
    )
    _require(len(nonqualifying_records) == 1, "unexpected_nonqualifying_record_count")
    _require(len(records) == qualifying_count + 1, "unexpected_total_record_count")
    _require(all(record["mode"] == "dry_run" for record in records), "non_dry_run_record")
    _require(
        all(record["synthetic_profile"] is True for record in records),
        "non_synthetic_profile_record",
    )
    _require(
        all(record["final_submit_clicked"] is False for record in records),
        "final_submit_clicked_in_phase_a",
    )
    _require(
        len({record["run_id"] for record in records}) == len(records),
        "duplicate_phase_a_run_id",
    )
    _require(
        len(
            {
                (
                    record["region"],
                    record["site"],
                    record["posting_id"],
                )
                for record in qualifying_records
            }
        )
        == qualifying_count,
        "duplicate_qualifying_target",
    )

    sources = _load_csv(sources_path)
    # Every canonical record has one source receipt, plus the preserved source
    # receipt for the superseded D8-043 manual boundary.
    _require(len(sources) == len(records) + 1, "unexpected_source_receipt_count")
    _require(
        all(source["retained_record_count"] == "1" for source in sources),
        "unexpected_retained_record_count",
    )
    _require(
        all(_DIGITS.fullmatch(source["workflow_run_id"]) for source in sources),
        "invalid_workflow_run_id",
    )
    _require(
        all(_DIGITS.fullmatch(source["artifact_id"]) for source in sources),
        "invalid_artifact_id",
    )
    _require(
        all(_HEX64.fullmatch(source["artifact_digest"]) for source in sources),
        "invalid_artifact_digest",
    )
    _require(
        len({source["artifact_id"] for source in sources}) == len(sources),
        "duplicate_artifact_id",
    )
    _require(
        len(
            {
                (source["workflow_run_id"], source["artifact_id"])
                for source in sources
            }
        )
        == len(sources),
        "duplicate_source_receipt",
    )

    source_run_ids = {source["workflow_run_id"] for source in sources}
    archive_results: list[dict[str, Any]] = []
    for record in records:
        match = _ACTIONS_RUN.fullmatch(record["source_reference"])
        _require(bool(match), record["source_reference"])
        if match is None:
            raise AssertionError(record["source_reference"])
        _require(match.group(1) in source_run_ids, (record["run_id"], match.group(1)))

        archive = verify_phase_a_external_archive(
            record,
            baseline_path=baseline_path,
        )
        if record["qualifies_for_dry_run_matrix"] is True:
            _require(archive["required"] is True, (record["run_id"], "archive_not_required"))
            _require(archive["verified"] is True, (record["run_id"], archive))
            _require(archive["errors"] == [], (record["run_id"], archive["errors"]))
            _require(bool(archive["archive_path"]), (record["run_id"], "archive_path_missing"))
        else:
            _require(archive["required"] is False, (record["run_id"], "archive_unexpectedly_required"))
            _require(archive["verified"] is True, (record["run_id"], archive))
        archive_results.append(
            {
                "run_id": record["run_id"],
                "required": archive["required"],
                "verified": archive["verified"],
                "archive_path": archive["archive_path"],
                "errors": archive["errors"],
            }
        )

    supersession = _verify_supersession(supersession_path)
    _require(_EXPECTED_STALE_SOURCE in sources, "expected_stale_source_missing")
    _require(
        not any(
            record["run_id"] == supersession["superseded"]["run_id"]
            for record in records
        ),
        "superseded_run_still_canonical",
    )
    replacements = [
        record
        for record in records
        if record["run_id"] == supersession["superseding"]["run_id"]
    ]
    _require(len(replacements) == 1, "superseding_record_count_mismatch")
    _require(
        replacements[0]["qualifies_for_dry_run_matrix"] is True,
        "superseding_record_not_qualifying",
    )
    _require(
        replacements[0]["final_submit_clicked"] is False,
        "superseding_record_clicked_final_submit",
    )

    day14_supersession = verify_day14_supersession_ledger(
        path=day14_supersession_path,
        records=records,
        sources=sources,
        evidence_root=evidence_root,
    )

    readiness = read_lever_pilot_readiness(
        baseline_path=baseline_path,
        ledger_path=missing_runtime_ledger,
    )
    committed_json = _load_json(readiness_json_path)
    committed_markdown = readiness_markdown_path.read_text(encoding="utf-8")
    _require(readiness == committed_json, "committed_readiness_json_drift")
    _require(
        render_readiness_markdown(readiness) == committed_markdown,
        "committed_readiness_markdown_drift",
    )

    summary = readiness["summary"]
    expected = {
        "record_count": len(records),
        "qualifying_dry_run_count": qualifying_count,
        "distinct_site_count": qualifying_count,
        "manual_challenge_boundary_count": 1,
        "manual_challenge_encounter_count": 1,
        "manual_challenge_violation_count": 0,
        "nonqualifying_dry_run_count": 1,
        "phase_a_artifact_verification_failure_count": 0,
        "phase_a_external_archive_failure_count": 0,
        "phase_a_inspection_failure_count": 0,
        "duplicate_submission_count": 0,
        "false_submitted_count": 0,
        "canonical_maturity": "dry_run",
        "promotion_ready": False,
        "supervised_confirmed_count": 0,
    }
    _require(
        readiness["baseline_record_count"] == len(records),
        "baseline_record_count_mismatch",
    )
    _require(readiness["runtime_record_count"] == 0, "unexpected_runtime_record_count")
    for key, expected_value in expected.items():
        _require(summary[key] == expected_value, (key, summary[key], expected_value))
    _require(set(summary["regions_covered"]) == {"eu", "global"}, "region_coverage_mismatch")
    _require(
        summary["gates"][
            "all_qualifying_phase_a_records_have_durable_external_archives"
        ]
        is True,
        "external_archive_gate_not_satisfied",
    )
    _require(
        summary["gates"]["global_and_eu_hosts_covered"] is True,
        "host_coverage_gate_not_satisfied",
    )
    target_reached = qualifying_count == _TARGET_QUALIFYING_DRY_RUNS
    _require(
        summary["gates"]["thirty_qualifying_dry_runs"] is target_reached,
        "qualifying_dry_run_gate_mismatch",
    )
    _require(
        summary["gates"]["thirty_distinct_lever_sites"] is target_reached,
        "distinct_site_gate_mismatch",
    )
    _require(
        summary["gates"]["explicit_separate_promotion_approval"] is False,
        "unexpected_promotion_approval",
    )

    (output_root / "lever-pilot-readiness.json").write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "lever-pilot-readiness.md").write_text(
        render_readiness_markdown(readiness),
        encoding="utf-8",
    )
    result = {
        "schema_version": "1.1",
        "passed": True,
        "record_count": len(records),
        "source_receipt_count": len(sources),
        "qualifying_dry_run_count": summary["qualifying_dry_run_count"],
        "distinct_site_count": summary["distinct_site_count"],
        "manual_challenge_boundary_count": summary[
            "manual_challenge_boundary_count"
        ],
        "phase_a_target_reached": target_reached,
        "supersession": {
            "superseded_run_id": supersession["superseded"]["run_id"],
            "superseding_review_id": "D8-043",
            "quota_credit_counted_once": supersession["safety"][
                "quota_credit_counted_once"
            ],
        },
        "day14_supersession": day14_supersession,
        "archive_results": archive_results,
        "safety": {
            "final_submit_clicked": False,
            "maturity_promoted": False,
            "real_submission_enabled": False,
        },
    }
    (output_root / "lever-phase-a-checkpoint-verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    parser.add_argument("--output-root", type=Path, default=Path("evidence-ci"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = verify_checkpoint(
        evidence_root=args.evidence_root,
        output_root=args.output_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
