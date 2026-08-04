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
    assert value["schema_version"] == "1.0"
    assert value["reason"] == "stronger_exact_target_ready_evidence"
    assert value["target"] == {
        "region": "eu",
        "site": "lever",
        "posting_id": "065f4538-7347-4207-909f-4ea68f63b4af",
    }

    superseded = value["superseded"]
    assert superseded["run_id"] == "github-actions-30337038142-1"
    assert superseded["pre_submit_state"] == "manual_challenge_handoff"
    assert superseded["final_status"] == "needs_review"
    assert superseded["handoff_reason"] == "captcha_detected"
    assert superseded["source_reference"].endswith("/30337038142")
    assert superseded["region"] == "eu"
    assert superseded["site"] == "lever"
    assert superseded["posting_id"] == "065f4538-7347-4207-909f-4ea68f63b4af"

    superseding = value["superseding"]
    assert superseding["run_id"] == "github-actions-30871406281-ready-d8-043"
    assert superseding["artifact_path"] == (
        "lever-phase-a-artifacts/D8-043/lever-phase-a-report.json"
    )
    assert superseding["pre_submit_state"] == "ready_to_submit"
    assert superseding["final_status"] == "dry_run_passed"
    assert superseding["source_reference"].endswith("/30871406281")

    assert value["safety"] == {
        "final_submit_clicked": False,
        "historical_boundary_preserved": True,
        "quota_credit_counted_once": True,
    }
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

    assert _MIN_QUALIFYING_DRY_RUNS <= qualifying_count <= _TARGET_QUALIFYING_DRY_RUNS
    assert len(nonqualifying_records) == 1
    assert len(records) == qualifying_count + 1
    assert all(record["mode"] == "dry_run" for record in records)
    assert all(record["synthetic_profile"] is True for record in records)
    assert all(record["final_submit_clicked"] is False for record in records)
    assert len({record["run_id"] for record in records}) == len(records)
    assert len(
        {
            (
                record["region"],
                record["site"],
                record["posting_id"],
            )
            for record in qualifying_records
        }
    ) == qualifying_count

    sources = _load_csv(sources_path)
    # Every canonical record has one source receipt, plus the preserved source
    # receipt for the superseded D8-043 manual boundary.
    assert len(sources) == len(records) + 1
    assert all(source["retained_record_count"] == "1" for source in sources)
    assert all(_DIGITS.fullmatch(source["workflow_run_id"]) for source in sources)
    assert all(_DIGITS.fullmatch(source["artifact_id"]) for source in sources)
    assert all(_HEX64.fullmatch(source["artifact_digest"]) for source in sources)
    assert len({source["artifact_id"] for source in sources}) == len(sources)
    assert len(
        {
            (source["workflow_run_id"], source["artifact_id"])
            for source in sources
        }
    ) == len(sources)

    source_run_ids = {source["workflow_run_id"] for source in sources}
    archive_results: list[dict[str, Any]] = []
    for record in records:
        match = _ACTIONS_RUN.fullmatch(record["source_reference"])
        assert match, record["source_reference"]
        assert match.group(1) in source_run_ids

        archive = verify_phase_a_external_archive(
            record,
            baseline_path=baseline_path,
        )
        if record["qualifies_for_dry_run_matrix"] is True:
            assert archive["required"] is True
            assert archive["verified"] is True, (record["run_id"], archive)
            assert archive["errors"] == []
            assert archive["archive_path"]
        else:
            assert archive["required"] is False
            assert archive["verified"] is True
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
    assert _EXPECTED_STALE_SOURCE in sources
    assert not any(
        record["run_id"] == supersession["superseded"]["run_id"]
        for record in records
    )
    replacements = [
        record
        for record in records
        if record["run_id"] == supersession["superseding"]["run_id"]
    ]
    assert len(replacements) == 1
    assert replacements[0]["qualifies_for_dry_run_matrix"] is True
    assert replacements[0]["final_submit_clicked"] is False

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
    assert readiness == committed_json
    assert render_readiness_markdown(readiness) == committed_markdown

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
    assert readiness["baseline_record_count"] == len(records)
    assert readiness["runtime_record_count"] == 0
    for key, expected_value in expected.items():
        assert summary[key] == expected_value, (key, summary[key], expected_value)
    assert set(summary["regions_covered"]) == {"eu", "global"}
    assert summary["gates"][
        "all_qualifying_phase_a_records_have_durable_external_archives"
    ] is True
    assert summary["gates"]["global_and_eu_hosts_covered"] is True
    target_reached = qualifying_count == _TARGET_QUALIFYING_DRY_RUNS
    assert summary["gates"]["thirty_qualifying_dry_runs"] is target_reached
    assert summary["gates"]["thirty_distinct_lever_sites"] is target_reached
    assert summary["gates"]["explicit_separate_promotion_approval"] is False

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
