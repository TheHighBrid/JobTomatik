#!/usr/bin/env python3
"""Import the validated Lever Phase A corpus resweep as a 20-run checkpoint."""

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
from scripts.finalize_lever_phase_a_ready_compatible import validate_ready_report

EXPECTED_REVIEW_IDS = {
    "D8-005", "D8-006", "D8-007", "D8-008", "D8-011",
    "D8-012", "D8-015", "D8-017", "D8-021", "D8-022",
    "D8-023", "D8-026", "D8-028", "D8-029", "D8-032",
    "D8-033", "D8-035", "D8-039", "D8-043",
}
RECOVERED_REVIEW_IDS = {"D8-011", "D8-022"}
SUPERSEDED_RUN_ID = "github-actions-30337038142-1"
SUPERSEDED_KEY = ("lever", "065f4538-7347-4207-909f-4ea68f63b4af", "eu")


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def append_one(
    target: Path,
    incoming: Path,
    unique_fields: tuple[str, ...],
) -> dict[str, str]:
    fields, existing = read_rows(target)
    incoming_fields, rows = read_rows(incoming)
    assert fields == incoming_fields, (target, fields, incoming_fields)
    assert len(rows) == 1, (incoming, len(rows))
    row = rows[0]
    assert not any(
        all(old.get(field) == row.get(field) for field in unique_fields)
        for old in existing
    ), ("duplicate import", target, unique_fields, row)
    with target.open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fields, lineterminator="\n").writerow(row)
    return row


def target_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("site") or "").strip().lower(),
        str(row.get("posting_id") or "").strip().lower(),
        str(row.get("region") or "").strip().lower(),
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finalization_ids(directory: Path) -> set[str]:
    return {
        path.stem.removeprefix("lever-phase-a-finalization-")
        for path in directory.glob("lever-phase-a-finalization-*.json")
    }


def prepare_baseline(baseline_path: Path) -> dict[str, str]:
    fields, raw_rows = read_rows(baseline_path)
    typed_rows = load_phase_a_baseline(baseline_path)
    assert len(raw_rows) == len(typed_rows) == 3
    assert sum(
        row.get("qualifies_for_dry_run_matrix") is True for row in typed_rows
    ) == 1

    superseded = [
        row for row in raw_rows
        if row.get("run_id") == SUPERSEDED_RUN_ID
        and target_key(row) == SUPERSEDED_KEY
        and row.get("pre_submit_state") == "manual_challenge_handoff"
        and row.get("final_status") == "needs_review"
        and row.get("handoff_reason") == "captcha_detected"
    ]
    assert len(superseded) == 1, superseded
    retained = [row for row in raw_rows if row.get("run_id") != SUPERSEDED_RUN_ID]
    assert len(retained) == 2
    write_rows(baseline_path, fields, retained)
    return superseded[0]


def copy_packages(original: Path, recovered: Path, evidence: Path) -> list[str]:
    assert original.is_dir(), original
    assert recovered.is_dir(), recovered
    original_ids = finalization_ids(original)
    recovered_ids = finalization_ids(recovered)
    assert len(original_ids) == 17, sorted(original_ids)
    assert recovered_ids == RECOVERED_REVIEW_IDS, sorted(recovered_ids)
    assert original_ids | recovered_ids == EXPECTED_REVIEW_IDS
    shutil.copytree(original, evidence, dirs_exist_ok=True)
    shutil.copytree(recovered, evidence, dirs_exist_ok=True)
    return sorted(EXPECTED_REVIEW_IDS)


def import_candidates(
    review_ids: list[str],
    evidence: Path,
    baseline_path: Path,
    sources_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    corpus = evidence / "lever-phase-a-target-corpus"
    imported: list[dict[str, str]] = []
    provenance: list[dict[str, Any]] = []

    for review_id in review_ids:
        candidate = append_one(
            baseline_path,
            evidence / f"lever-phase-a-candidate-{review_id}.csv",
            ("run_id",),
        )
        source = append_one(
            sources_path,
            evidence / f"lever-phase-a-source-{review_id}.csv",
            ("workflow_run_id", "artifact_id"),
        )
        finalization = json.loads(
            (evidence / f"lever-phase-a-finalization-{review_id}.json").read_text(
                encoding="utf-8"
            )
        )

        assert finalization["review_id"] == review_id
        assert finalization["workflow_run_id"] == source["workflow_run_id"]
        assert finalization["artifact_id"] == source["artifact_id"]
        assert finalization["artifact_digest"] == source["artifact_digest"]
        assert finalization["report_sha256"] == candidate["artifact_sha256"]
        assert finalization["final_submit_clicked"] is False
        assert candidate["pre_submit_state"] == "ready_to_submit"
        assert candidate["final_status"] == "dry_run_passed"
        assert candidate["source_reference"].endswith("/" + source["workflow_run_id"])

        report_path = evidence / candidate["artifact_path"]
        assert report_path.is_file()
        assert sha256(report_path) == candidate["artifact_sha256"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_ready_report(report, load_locked_target(review_id, corpus))
        assert report["final_submit_clicked"] is False

        archive = (
            evidence
            / "lever-phase-a-external-archives"
            / review_id
            / f"artifact-{source['artifact_id']}-{source['artifact_digest']}.zip"
        )
        assert archive.is_file(), archive
        assert sha256(archive) == source["artifact_digest"]

        imported.append(candidate)
        provenance.append(finalization)

    return imported, provenance


def write_supersession(
    evidence: Path,
    superseded: dict[str, str],
    imported: list[dict[str, str]],
) -> dict[str, Any]:
    superseding = [row for row in imported if target_key(row) == SUPERSEDED_KEY]
    assert len(superseding) == 1, superseding
    current = superseding[0]
    receipt = {
        "schema_version": "1.0",
        "reason": "stronger_exact_target_ready_evidence",
        "target": {
            "site": SUPERSEDED_KEY[0],
            "posting_id": SUPERSEDED_KEY[1],
            "region": SUPERSEDED_KEY[2],
        },
        "superseded": superseded,
        "superseding": {
            "run_id": current["run_id"],
            "artifact_path": current["artifact_path"],
            "artifact_sha256": current["artifact_sha256"],
            "source_reference": current["source_reference"],
            "pre_submit_state": current["pre_submit_state"],
            "final_status": current["final_status"],
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


def verify_final_state(baseline_path: Path, sources_path: Path) -> dict[str, int]:
    rows = load_phase_a_baseline(baseline_path)
    qualifying = [row for row in rows if row.get("qualifies_for_dry_run_matrix") is True]
    assert len(rows) == 21, len(rows)
    assert len(qualifying) == 20, len(qualifying)
    assert len({target_key(row) for row in rows}) == len(rows)
    assert len({row["run_id"] for row in rows}) == len(rows)
    assert len({row["site"] for row in qualifying}) == 20
    assert not any(row.get("final_submit_clicked") for row in rows)

    _, sources = read_rows(sources_path)
    assert len(sources) == 22, len(sources)
    assert len({(row["workflow_run_id"], row["artifact_id"]) for row in sources}) == 22
    return {
        "baseline_record_count": 21,
        "qualifying_dry_run_count": 20,
        "distinct_site_count": 20,
        "source_receipt_count": 22,
    }


def regenerate_readiness(evidence: Path) -> dict[str, Any]:
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
    assert readiness["baseline_record_count"] == 21
    assert summary["record_count"] == 21
    assert summary["qualifying_dry_run_count"] == 20
    assert summary["distinct_site_count"] == 20
    assert set(summary["regions_covered"]) == {"eu", "global"}
    assert summary["manual_challenge_boundary_count"] == 1
    assert summary["nonqualifying_dry_run_count"] == 1
    assert summary["canonical_maturity"] == "dry_run"
    assert summary["promotion_ready"] is False
    assert summary["duplicate_submission_count"] == 0
    assert summary["false_submitted_count"] == 0
    assert summary["phase_a_external_archive_failure_count"] == 0
    assert summary["phase_a_inspection_failure_count"] == 0
    assert summary["gates"][
        "all_qualifying_phase_a_records_have_durable_external_archives"
    ] is True
    assert summary["gates"]["global_and_eu_hosts_covered"] is True
    assert summary["gates"]["thirty_qualifying_dry_runs"] is False
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
    baseline_path = evidence / "lever-phase-a-baseline.csv"
    sources_path = evidence / "lever-phase-a-sources.csv"

    catalog = json.loads(
        next(args.catalog_dir.rglob("*.json")).read_text(encoding="utf-8")
    )
    review_ids = sorted(catalog.get("qualifying_review_ids") or [])
    assert set(review_ids) == EXPECTED_REVIEW_IDS, review_ids

    superseded = prepare_baseline(baseline_path)
    assert copy_packages(
        args.original_finalized,
        args.recovered_finalized,
        evidence,
    ) == review_ids
    imported, provenance = import_candidates(
        review_ids,
        evidence,
        baseline_path,
        sources_path,
    )
    supersession = write_supersession(evidence, superseded, imported)
    final_state = verify_final_state(baseline_path, sources_path)
    readiness_summary = regenerate_readiness(evidence)

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
