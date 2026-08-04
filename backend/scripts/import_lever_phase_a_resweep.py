#!/usr/bin/env python3
"""Import the validated Lever Phase A resweep into the canonical checkpoint."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from app.services.lever_phase_a_operator import load_locked_target
from app.services.lever_pilot_ingestion import (
    load_phase_a_baseline,
    render_readiness_markdown,
)
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness
from scripts.finalize_lever_phase_a_ready import validate_ready_report

EXPECTED_REVIEW_IDS = {
    "D8-005",
    "D8-006",
    "D8-007",
    "D8-008",
    "D8-011",
    "D8-012",
    "D8-015",
    "D8-017",
    "D8-021",
    "D8-022",
    "D8-023",
    "D8-026",
    "D8-028",
    "D8-029",
    "D8-032",
    "D8-033",
    "D8-035",
    "D8-039",
    "D8-043",
}
RECOVERED_REVIEW_IDS = {"D8-011", "D8-022"}
SUPERSEDED_TARGET = "eu:lever:065f4538-7347-4207-909f-4ea68f63b4af"
SUPERSEDED_RUN_ID = "github-actions-30337038142-1"
SUPERSEDING_REVIEW_ID = "D8-043"


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _append_one(
    target: Path,
    incoming: Path,
    unique_fields: tuple[str, ...],
) -> dict[str, str]:
    fields, existing = _read_rows(target)
    incoming_fields, rows = _read_rows(incoming)
    if fields != incoming_fields:
        raise AssertionError((target, fields, incoming_fields))
    if len(rows) != 1:
        raise AssertionError((incoming, len(rows)))
    row = rows[0]
    for old in existing:
        if all(old.get(key) == row.get(key) for key in unique_fields):
            raise AssertionError(("duplicate import", target, unique_fields, row))
    with target.open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(
            handle,
            fieldnames=fields,
            lineterminator="\n",
        ).writerow(row)
    return row


def _finalization_ids(directory: Path) -> set[str]:
    return {
        path.stem.removeprefix("lever-phase-a-finalization-")
        for path in directory.glob("lever-phase-a-finalization-*.json")
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_initial_state(baseline_path: Path) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    fields, raw_rows = _read_rows(baseline_path)
    typed_rows = load_phase_a_baseline(baseline_path)
    if len(raw_rows) != 3 or len(typed_rows) != 3:
        raise AssertionError((len(raw_rows), len(typed_rows)))
    if sum(row.get("qualifies_for_dry_run_matrix") is True for row in typed_rows) != 1:
        raise AssertionError("Expected one qualifying row before the resweep import")

    superseded = [
        row
        for row in raw_rows
        if row.get("target_identity") == SUPERSEDED_TARGET
        and row.get("run_id") == SUPERSEDED_RUN_ID
        and row.get("final_status") == "needs_review"
        and row.get("handoff_reason") == "captcha_detected"
        and row.get("valid_manual_challenge_handoff") == "true"
        and row.get("final_submit_clicked") == "false"
    ]
    if len(superseded) != 1:
        raise AssertionError(("superseded D8-043 row", superseded))
    return fields, raw_rows, superseded[0]


def _replace_superseded_row(
    baseline_path: Path,
    fields: list[str],
    raw_rows: list[dict[str, str]],
    superseded: dict[str, str],
) -> None:
    retained = [row for row in raw_rows if row is not superseded]
    if len(retained) != 2:
        raise AssertionError(len(retained))
    _write_rows(baseline_path, fields, retained)


def _copy_packages(original: Path, recovered: Path, evidence: Path) -> list[str]:
    if not original.is_dir() or not recovered.is_dir():
        raise AssertionError((original, recovered))
    original_ids = _finalization_ids(original)
    recovered_ids = _finalization_ids(recovered)
    if len(original_ids) != 17:
        raise AssertionError(sorted(original_ids))
    if recovered_ids != RECOVERED_REVIEW_IDS:
        raise AssertionError(sorted(recovered_ids))
    if original_ids | recovered_ids != EXPECTED_REVIEW_IDS:
        raise AssertionError(sorted(original_ids | recovered_ids))
    shutil.copytree(original, evidence, dirs_exist_ok=True)
    shutil.copytree(recovered, evidence, dirs_exist_ok=True)
    return sorted(EXPECTED_REVIEW_IDS)


def _import_candidates(
    *,
    review_ids: list[str],
    evidence: Path,
    corpus: Path,
    baseline_path: Path,
    sources_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    imported_rows: list[dict[str, str]] = []
    provenance: list[dict[str, Any]] = []

    for review_id in review_ids:
        candidate_path = evidence / f"lever-phase-a-candidate-{review_id}.csv"
        source_path = evidence / f"lever-phase-a-source-{review_id}.csv"
        finalization_path = evidence / f"lever-phase-a-finalization-{review_id}.json"
        if not candidate_path.is_file() or not source_path.is_file() or not finalization_path.is_file():
            raise AssertionError((candidate_path, source_path, finalization_path))

        candidate = _append_one(baseline_path, candidate_path, ("run_id",))
        source = _append_one(
            sources_path,
            source_path,
            ("workflow_run_id", "artifact_id"),
        )
        finalization = json.loads(finalization_path.read_text(encoding="utf-8"))

        if finalization.get("review_id") != review_id:
            raise AssertionError(finalization)
        if finalization.get("workflow_run_id") != source.get("workflow_run_id"):
            raise AssertionError((finalization, source))
        if finalization.get("artifact_id") != source.get("artifact_id"):
            raise AssertionError((finalization, source))
        if finalization.get("artifact_digest") != source.get("artifact_digest"):
            raise AssertionError((finalization, source))
        if finalization.get("report_sha256") != candidate.get("artifact_sha256"):
            raise AssertionError((finalization, candidate))
        if finalization.get("final_submit_clicked") is not False:
            raise AssertionError(finalization)
        if candidate.get("pre_submit_state") != "ready_to_submit":
            raise AssertionError(candidate)
        if candidate.get("final_status") != "dry_run_passed":
            raise AssertionError(candidate)
        if candidate.get("final_submit_clicked") != "false":
            raise AssertionError(candidate)
        if not candidate.get("source_reference", "").endswith(
            "/" + source["workflow_run_id"]
        ):
            raise AssertionError((candidate, source))

        report_path = evidence / candidate["artifact_path"]
        if not report_path.is_file() or _sha256(report_path) != candidate["artifact_sha256"]:
            raise AssertionError(report_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        target = load_locked_target(review_id, corpus)
        validate_ready_report(report, target)

        archive = (
            evidence
            / "lever-phase-a-external-archives"
            / review_id
            / (
                "artifact-"
                + source["artifact_id"]
                + "-"
                + source["artifact_digest"]
                + ".zip"
            )
        )
        if not archive.is_file() or _sha256(archive) != source["artifact_digest"]:
            raise AssertionError(archive)

        imported_rows.append(candidate)
        provenance.append(finalization)

    return imported_rows, provenance


def _write_supersession(
    evidence: Path,
    superseded: dict[str, str],
    imported_rows: list[dict[str, str]],
) -> dict[str, Any]:
    superseding = [
        row for row in imported_rows if row.get("review_id") == SUPERSEDING_REVIEW_ID
    ]
    if len(superseding) != 1:
        raise AssertionError(superseding)
    superseding_row = superseding[0]
    if superseding_row.get("target_identity") != SUPERSEDED_TARGET:
        raise AssertionError(superseding_row)
    receipt = {
        "schema_version": "1.0",
        "target_identity": SUPERSEDED_TARGET,
        "reason": "stronger_exact_target_ready_evidence",
        "superseded": superseded,
        "superseding": {
            "review_id": SUPERSEDING_REVIEW_ID,
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


def _assert_final_state(baseline_path: Path, sources_path: Path) -> dict[str, Any]:
    rows = load_phase_a_baseline(baseline_path)
    qualifying = [row for row in rows if row.get("qualifies_for_dry_run_matrix") is True]
    if len(rows) != 21:
        raise AssertionError(len(rows))
    if len(qualifying) != 20:
        raise AssertionError(len(qualifying))
    if len({row["site"] for row in qualifying}) != 20:
        raise AssertionError("Qualifying sites are not distinct")
    if len({row["target_identity"] for row in rows}) != len(rows):
        raise AssertionError("Canonical target identities are not unique")
    if len({row["run_id"] for row in rows}) != len(rows):
        raise AssertionError("Run IDs are not unique")
    if any(row.get("final_submit_clicked") for row in rows):
        raise AssertionError("A final-submit click was recorded")

    _, source_rows = _read_rows(sources_path)
    if len(source_rows) != 22:
        raise AssertionError(len(source_rows))
    if len(
        {
            (row["workflow_run_id"], row["artifact_id"])
            for row in source_rows
        }
    ) != len(source_rows):
        raise AssertionError("Source receipts are not unique")

    return {
        "baseline_record_count": len(rows),
        "qualifying_dry_run_count": len(qualifying),
        "distinct_site_count": len({row["site"] for row in qualifying}),
        "source_receipt_count": len(source_rows),
    }


def _regenerate_readiness(evidence: Path) -> dict[str, Any]:
    readiness = read_lever_pilot_readiness(
        baseline_path=evidence / "lever-phase-a-baseline.csv",
        ledger_path=evidence / ".missing-phase-b-runtime.jsonl",
    )
    (evidence / "lever-pilot-readiness.json").write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (evidence / "lever-pilot-readiness.md").write_text(
        render_readiness_markdown(readiness),
        encoding="utf-8",
    )
    summary = readiness["summary"]
    expected = {
        "baseline_record_count": 21,
        "record_count": 21,
        "qualifying_dry_run_count": 20,
        "distinct_site_count": 20,
        "manual_challenge_boundary_count": 1,
        "nonqualifying_dry_run_count": 1,
        "canonical_maturity": "dry_run",
        "promotion_ready": False,
        "duplicate_submission_count": 0,
        "false_submitted_count": 0,
        "phase_a_external_archive_failure_count": 0,
        "phase_a_inspection_failure_count": 0,
    }
    if readiness["baseline_record_count"] != expected.pop("baseline_record_count"):
        raise AssertionError(readiness["baseline_record_count"])
    for key, value in expected.items():
        if summary.get(key) != value:
            raise AssertionError((key, summary.get(key), value))
    if set(summary.get("regions_covered") or []) != {"eu", "global"}:
        raise AssertionError(summary.get("regions_covered"))
    if summary["gates"].get(
        "all_qualifying_phase_a_records_have_durable_external_archives"
    ) is not True:
        raise AssertionError(summary["gates"])
    if summary["gates"].get("global_and_eu_hosts_covered") is not True:
        raise AssertionError(summary["gates"])
    if summary["gates"].get("thirty_qualifying_dry_runs") is not False:
        raise AssertionError(summary["gates"])
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-dir", required=True, type=Path)
    parser.add_argument("--original-finalized", required=True, type=Path)
    parser.add_argument("--recovered-finalized", required=True, type=Path)
    parser.add_argument("--evidence-dir", default=Path("evidence"), type=Path)
    parser.add_argument("--source-run-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence = args.evidence_dir
    corpus = evidence / "lever-phase-a-target-corpus"
    baseline_path = evidence / "lever-phase-a-baseline.csv"
    sources_path = evidence / "lever-phase-a-sources.csv"

    catalog = json.loads(
        next(args.catalog_dir.rglob("*.json")).read_text(encoding="utf-8")
    )
    review_ids = sorted(catalog.get("qualifying_review_ids") or [])
    if set(review_ids) != EXPECTED_REVIEW_IDS:
        raise AssertionError(review_ids)

    fields, raw_rows, superseded = _assert_initial_state(baseline_path)
    _replace_superseded_row(baseline_path, fields, raw_rows, superseded)
    package_ids = _copy_packages(
        args.original_finalized,
        args.recovered_finalized,
        evidence,
    )
    if package_ids != review_ids:
        raise AssertionError((package_ids, review_ids))

    imported_rows, provenance = _import_candidates(
        review_ids=review_ids,
        evidence=evidence,
        corpus=corpus,
        baseline_path=baseline_path,
        sources_path=sources_path,
    )
    supersession = _write_supersession(evidence, superseded, imported_rows)
    final_state = _assert_final_state(baseline_path, sources_path)
    readiness_summary = _regenerate_readiness(evidence)

    summary = {
        "schema_version": "1.1",
        "repository": os.environ.get("GITHUB_REPOSITORY", "TheHighBrid/JobTomatik"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "head_sha": os.environ.get("GITHUB_SHA", ""),
        "source_resweep_run_id": args.source_run_id,
        "attempted_target_count": catalog["attempted_target_count"],
        "outcome_counts": catalog["outcome_counts"],
        "qualifying_count_before": 1,
        "qualifying_count_added": 19,
        "qualifying_count_after": 20,
        "retained_review_ids": review_ids,
        "retained_provenance": provenance,
        "supersession": supersession,
        "safety": catalog["safety"],
        "results": catalog["results"],
        "final_state": final_state,
        "readiness_summary": readiness_summary,
    }
    (evidence / "lever-phase-a-corpus-resweep-2026-08-04.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for path in evidence.glob("lever-phase-a-finalization-*.json"):
        path.unlink()

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
