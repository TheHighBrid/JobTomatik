#!/usr/bin/env python3
"""Import independently finalized Lever Day 13 packages into a staged checkpoint."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from app.services.lever_pilot_ingestion import (
    load_phase_a_baseline,
    render_readiness_markdown,
)
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness


def _read_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _append_rows(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    fields, _ = _read_rows(path)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        for row in rows:
            if list(row) != fields:
                raise ValueError(f"CSV schema mismatch for {path}")
            writer.writerow(row)


def _target_identity(row: Dict[str, str]) -> Tuple[str, str, str]:
    return (
        str(row.get("region") or "").strip().lower(),
        str(row.get("site") or "").strip().lower(),
        str(row.get("posting_id") or "").strip().lower(),
    )


def import_packages(
    *,
    package_root: Path,
    evidence_root: Path,
    minimum_count: int,
) -> Dict[str, object]:
    incoming = package_root / "evidence"
    if not incoming.is_dir():
        raise ValueError(f"Missing package evidence root: {incoming}")

    candidate_paths = sorted(incoming.glob("lever-phase-a-candidate-D8-*.csv"))
    if len(candidate_paths) < minimum_count:
        raise ValueError(
            f"Day 13 retained only {len(candidate_paths)} qualifying packages; "
            f"at least {minimum_count} are required"
        )

    baseline_path = evidence_root / "lever-phase-a-baseline.csv"
    sources_path = evidence_root / "lever-phase-a-sources.csv"
    baseline_fields, baseline_rows = _read_rows(baseline_path)
    source_fields, source_rows = _read_rows(sources_path)

    existing_run_ids = {row.get("run_id") for row in baseline_rows}
    existing_targets = {_target_identity(row) for row in baseline_rows}
    existing_sources = {
        (row.get("workflow_run_id"), row.get("artifact_id"))
        for row in source_rows
    }

    candidates: List[Dict[str, str]] = []
    sources: List[Dict[str, str]] = []
    review_ids: List[str] = []
    for candidate_path in candidate_paths:
        review_id = candidate_path.stem.removeprefix("lever-phase-a-candidate-")
        source_path = incoming / f"lever-phase-a-source-{review_id}.csv"
        if not source_path.is_file():
            raise ValueError(f"Missing source receipt for {review_id}")

        candidate_fields, candidate_rows = _read_rows(candidate_path)
        incoming_source_fields, incoming_source_rows = _read_rows(source_path)
        if candidate_fields != baseline_fields or len(candidate_rows) != 1:
            raise ValueError(f"Invalid candidate package for {review_id}")
        if incoming_source_fields != source_fields or len(incoming_source_rows) != 1:
            raise ValueError(f"Invalid source package for {review_id}")

        candidate = candidate_rows[0]
        source = incoming_source_rows[0]
        run_id = candidate.get("run_id")
        identity = _target_identity(candidate)
        source_key = (source.get("workflow_run_id"), source.get("artifact_id"))
        if not all(identity):
            raise ValueError(f"Incomplete target identity for {review_id}")
        if run_id in existing_run_ids or any(row.get("run_id") == run_id for row in candidates):
            raise ValueError(f"Duplicate run ID for {review_id}")
        if identity in existing_targets or any(_target_identity(row) == identity for row in candidates):
            raise ValueError(f"Duplicate target identity for {review_id}")
        if source_key in existing_sources or any(
            (row.get("workflow_run_id"), row.get("artifact_id")) == source_key
            for row in sources
        ):
            raise ValueError(f"Duplicate source receipt for {review_id}")
        if candidate.get("pre_submit_state") != "ready_to_submit":
            raise ValueError(f"Candidate {review_id} is not ready_to_submit")
        if candidate.get("final_status") != "dry_run_passed":
            raise ValueError(f"Candidate {review_id} did not dry-run pass")

        candidates.append(candidate)
        sources.append(source)
        review_ids.append(review_id)

    staged = evidence_root.parent / ".lever-day13-staged-evidence"
    shutil.rmtree(staged, ignore_errors=True)
    shutil.copytree(evidence_root, staged)
    shutil.copytree(incoming, staged, dirs_exist_ok=True)
    _append_rows(staged / baseline_path.name, candidates)
    _append_rows(staged / sources_path.name, sources)

    loaded = load_phase_a_baseline(staged / baseline_path.name)
    readiness = read_lever_pilot_readiness(
        baseline_path=staged / baseline_path.name,
        ledger_path=staged / ".missing-phase-b-runtime.jsonl",
    )
    summary = readiness["summary"]
    expected_qualifying = 20 + len(candidates)
    expected_records = 21 + len(candidates)
    if readiness["baseline_record_count"] != expected_records:
        raise ValueError("Unexpected Day 13 baseline record count")
    if summary["qualifying_dry_run_count"] != expected_qualifying:
        raise ValueError("Unexpected Day 13 qualifying count")
    if summary["distinct_site_count"] != expected_qualifying:
        raise ValueError("Day 13 did not retain distinct sites")
    if set(summary["regions_covered"]) != {"eu", "global"}:
        raise ValueError("Day 13 lost required host coverage")
    if summary["phase_a_external_archive_failure_count"] != 0:
        raise ValueError("Day 13 introduced an external archive failure")
    if summary["duplicate_submission_count"] != 0:
        raise ValueError("Day 13 introduced a duplicate submission")
    if summary["false_submitted_count"] != 0:
        raise ValueError("Day 13 introduced a false submitted record")
    if summary["canonical_maturity"] != "dry_run" or summary["promotion_ready"] is not False:
        raise ValueError("Day 13 changed Lever maturity or promotion state")
    if any(row.get("final_submit_clicked") for row in loaded):
        raise ValueError("Day 13 recorded a final-submit click")

    (staged / "lever-pilot-readiness.json").write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (staged / "lever-pilot-readiness.md").write_text(
        render_readiness_markdown(readiness),
        encoding="utf-8",
    )
    result = {
        "schema_version": "1.0",
        "retained_review_ids": review_ids,
        "qualifying_count_before": 20,
        "qualifying_count_added": len(candidates),
        "qualifying_count_after": expected_qualifying,
        "distinct_site_count_after": expected_qualifying,
        "baseline_record_count_after": expected_records,
        "regions_covered": summary["regions_covered"],
        "safety": {
            "final_submit_clicked": False,
            "duplicate_submission_count": 0,
            "false_submitted_count": 0,
            "external_archive_failure_count": 0,
            "maturity_promoted": False,
        },
    }
    (staged / "lever-phase-a-day13-2026-08-04.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    shutil.copytree(staged, evidence_root, dirs_exist_ok=True)
    shutil.rmtree(staged)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--evidence-root", default="evidence")
    parser.add_argument("--minimum-count", type=int, default=5)
    args = parser.parse_args()
    result = import_packages(
        package_root=Path(args.package_root),
        evidence_root=Path(args.evidence_root),
        minimum_count=args.minimum_count,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
