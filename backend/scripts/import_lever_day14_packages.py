#!/usr/bin/env python3
"""Atomically replace Day 13 evidence and add the final two Lever dry runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from app.services.lever_phase_a_operator import load_locked_target
from app.services.lever_pilot_ingestion import (
    load_phase_a_baseline,
    render_readiness_markdown,
)
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness
from scripts.finalize_lever_phase_a_ready_compatible import validate_ready_report


EXPECTED_REPLACEMENTS = {
    "D8-009",
    "D8-010",
    "D8-018",
    "D8-020",
    "D8-030",
    "D8-034",
    "D8-036",
    "D8-040",
}
EXPECTED_ADDITIONS = {"D8-004", "D8-016"}
EXPECTED_REVIEW_IDS = EXPECTED_REPLACEMENTS | EXPECTED_ADDITIONS
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DIGITS = re.compile(r"[1-9][0-9]*")


class Day14ImportError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _write_rows(path: Path, fields: List[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            if list(row) != fields:
                raise Day14ImportError(f"CSV schema mismatch for {path}")
            writer.writerow({field: row.get(field, "") for field in fields})


def _identity(row: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(row.get("region") or "").strip().lower(),
        str(row.get("site") or "").strip().lower(),
        str(row.get("posting_id") or "").strip().lower(),
    )


def _source_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    return (
        str(row.get("workflow_run_id") or "").strip(),
        str(row.get("artifact_id") or "").strip(),
    )


def _review_id_from_artifact_path(value: Any) -> str:
    path = PurePosixPath(str(value or "").strip())
    if (
        len(path.parts) == 3
        and path.parts[0] == "lever-phase-a-artifacts"
        and re.fullmatch(r"D8-[0-9]{3}", path.parts[1])
        and path.parts[2] == "lever-phase-a-report.json"
    ):
        return path.parts[1]
    return ""


def _load_one_row(path: Path, expected_fields: List[str]) -> Dict[str, str]:
    fields, rows = _read_rows(path)
    if fields != expected_fields or len(rows) != 1:
        raise Day14ImportError(f"Invalid one-row CSV: {path}")
    return rows[0]


def _validate_source(source: Mapping[str, Any]) -> None:
    run_id = str(source.get("workflow_run_id") or "")
    artifact_id = str(source.get("artifact_id") or "")
    digest = str(source.get("artifact_digest") or "")
    if not _DIGITS.fullmatch(run_id):
        raise Day14ImportError("Invalid source workflow run ID")
    if not _DIGITS.fullmatch(artifact_id):
        raise Day14ImportError("Invalid source artifact ID")
    if not _HEX64.fullmatch(digest):
        raise Day14ImportError("Invalid source artifact digest")
    if str(source.get("retained_record_count") or "") != "1":
        raise Day14ImportError("Invalid source retained-record count")


def _source_archive_path(root: Path, review_id: str, source: Mapping[str, Any]) -> Path:
    return (
        root
        / "lever-phase-a-external-archives"
        / review_id
        / (
            f"artifact-{source['artifact_id']}-"
            f"{source['artifact_digest']}.zip"
        )
    )


def _replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise Day14ImportError(
            f"Expected one {label} block in {path}, found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _write_day14_verifier(root: Path) -> None:
    service = root / "backend/app/services/lever_day14_supersession.py"
    service.write_text(
        '''"""Verification for the final Lever Phase A evidence replacements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


EXPECTED_REPLACEMENTS = {
    "D8-009", "D8-010", "D8-018", "D8-020",
    "D8-030", "D8-034", "D8-036", "D8-040",
}
EXPECTED_ADDITIONS = {"D8-004", "D8-016"}


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("region") or "").strip().lower(),
        str(row.get("site") or "").strip().lower(),
        str(row.get("posting_id") or "").strip().lower(),
    )


def _source_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("workflow_run_id") or "").strip(),
        str(row.get("artifact_id") or "").strip(),
    )


def _safe_historical_archive(evidence_root: Path, value: Any) -> Path:
    relative = PurePosixPath(str(value or "").strip())
    if relative.is_absolute() or ".." in relative.parts:
        raise AssertionError("unsafe_historical_archive_path")
    path = (evidence_root / Path(*relative.parts)).resolve()
    path.relative_to(evidence_root.resolve())
    return path


def verify_day14_supersession_ledger(
    *,
    path: Path,
    records: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
    evidence_root: Path,
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["schema_version"] == "1.0"
    assert value["reason"] == "stronger_serialized_control_evidence"
    assert value["safety"] == {
        "final_submit_clicked": False,
        "historical_archives_preserved": True,
        "quota_credit_counted_once": True,
        "replacement_count": 8,
        "addition_count": 2,
    }

    current_runs = {str(record.get("run_id") or "") for record in records}
    current_sources = {_source_key(source) for source in sources}
    replacements = list(value.get("replacements") or [])
    additions = list(value.get("additions") or [])
    assert {item["review_id"] for item in replacements} == EXPECTED_REPLACEMENTS
    assert {item["review_id"] for item in additions} == EXPECTED_ADDITIONS
    assert len(replacements) == len(EXPECTED_REPLACEMENTS)
    assert len(additions) == len(EXPECTED_ADDITIONS)

    replacement_summaries = []
    for item in replacements:
        old_row = item["superseded"]["record"]
        new_row = item["superseding"]["record"]
        old_source = item["superseded"]["source"]
        new_source = item["superseding"]["source"]
        target = (
            item["target"]["region"],
            item["target"]["site"],
            item["target"]["posting_id"],
        )
        assert _identity(old_row) == target
        assert _identity(new_row) == target
        assert old_row["run_id"] not in current_runs
        assert new_row["run_id"] in current_runs
        assert _source_key(old_source) not in current_sources
        assert _source_key(new_source) in current_sources
        assert new_row["pre_submit_state"] == "ready_to_submit"
        assert new_row["final_status"] == "dry_run_passed"

        archive_path = _safe_historical_archive(
            evidence_root,
            item["superseded"]["archive_path"],
        )
        assert archive_path.is_file()
        assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == (
            old_source["artifact_digest"]
        )
        replacement_summaries.append({
            "review_id": item["review_id"],
            "superseded_run_id": old_row["run_id"],
            "superseding_run_id": new_row["run_id"],
            "historical_archive": archive_path.relative_to(
                evidence_root
            ).as_posix(),
        })

    addition_summaries = []
    for item in additions:
        row = item["record"]
        source = item["source"]
        target = (
            item["target"]["region"],
            item["target"]["site"],
            item["target"]["posting_id"],
        )
        assert _identity(row) == target
        assert row["run_id"] in current_runs
        assert _source_key(source) in current_sources
        assert row["pre_submit_state"] == "ready_to_submit"
        assert row["final_status"] == "dry_run_passed"
        addition_summaries.append({
            "review_id": item["review_id"],
            "run_id": row["run_id"],
        })

    return {
        "replacement_count": len(replacement_summaries),
        "addition_count": len(addition_summaries),
        "replacements": replacement_summaries,
        "additions": addition_summaries,
        "quota_credit_counted_once": True,
    }


__all__ = ["verify_day14_supersession_ledger"]
''',
        encoding="utf-8",
    )

    checkpoint = root / "backend/scripts/verify_lever_phase_a_checkpoint.py"
    _replace_once(
        checkpoint,
        '''from app.services.lever_phase_a_archive import verify_phase_a_external_archive
''',
        '''from app.services.lever_day14_supersession import (
    verify_day14_supersession_ledger,
)
from app.services.lever_phase_a_archive import verify_phase_a_external_archive
''',
        "day14 verifier import",
    )
    _replace_once(
        checkpoint,
        "_MIN_QUALIFYING_DRY_RUNS = 28\n",
        "_MIN_QUALIFYING_DRY_RUNS = 30\n",
        "final checkpoint floor",
    )
    _replace_once(
        checkpoint,
        '''    supersession_path = evidence_root / "lever-phase-a-supersessions.json"
    missing_runtime_ledger = output_root / "missing-phase-b.jsonl"
''',
        '''    supersession_path = evidence_root / "lever-phase-a-supersessions.json"
    day14_supersession_path = (
        evidence_root / "lever-phase-a-day14-supersessions.json"
    )
    missing_runtime_ledger = output_root / "missing-phase-b.jsonl"
''',
        "day14 ledger path",
    )
    _replace_once(
        checkpoint,
        '''    assert replacements[0]["qualifies_for_dry_run_matrix"] is True
    assert replacements[0]["final_submit_clicked"] is False

    readiness = read_lever_pilot_readiness(
''',
        '''    assert replacements[0]["qualifies_for_dry_run_matrix"] is True
    assert replacements[0]["final_submit_clicked"] is False

    day14_supersession = verify_day14_supersession_ledger(
        path=day14_supersession_path,
        records=records,
        sources=sources,
        evidence_root=evidence_root,
    )

    readiness = read_lever_pilot_readiness(
''',
        "day14 ledger verification",
    )
    _replace_once(
        checkpoint,
        '''        "supersession": {
            "superseded_run_id": supersession["superseded"]["run_id"],
            "superseding_review_id": "D8-043",
            "quota_credit_counted_once": supersession["safety"][
                "quota_credit_counted_once"
            ],
        },
        "archive_results": archive_results,
''',
        '''        "supersession": {
            "superseded_run_id": supersession["superseded"]["run_id"],
            "superseding_review_id": "D8-043",
            "quota_credit_counted_once": supersession["safety"][
                "quota_credit_counted_once"
            ],
        },
        "day14_supersession": day14_supersession,
        "archive_results": archive_results,
''',
        "day14 verification result",
    )

    progression = root / "backend/tests/test_lever_phase_a_checkpoint_progression.py"
    _replace_once(
        progression,
        '''    assert 28 <= result["qualifying_dry_run_count"] <= 30
''',
        '''    assert result["qualifying_dry_run_count"] == 30
''',
        "final progression assertion",
    )


def _refresh_freeze(root: Path) -> None:
    freeze_path = root / "docs/operations/lever-phase-2-measurement-freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze["contract_version"] = "2026-08-04.day14.1"
    freeze["amendment"]["previous_contract_version"] = "2026-08-04.day13.2"
    freeze["amendment"]["purpose"] = (
        "Lock the final 30-site Lever Phase A dry-run checkpoint, including eight "
        "serialized-evidence replacements, two new distinct sites, and preserved "
        "historical artifact archives."
    )
    service = "backend/app/services/lever_day14_supersession.py"
    if service not in freeze["canonical_inputs"]:
        freeze["canonical_inputs"].append(service)
    freeze["canonical_inputs"] = sorted(freeze["canonical_inputs"])

    blobs: Dict[str, str] = {}
    for value in freeze["canonical_inputs"]:
        path = root / value
        if not path.is_file():
            raise Day14ImportError(f"Frozen canonical input is missing: {value}")
        blobs[value] = subprocess.check_output(
            ["git", "hash-object", str(path)],
            cwd=root,
            text=True,
        ).strip()
    freeze["locked_input_blobs"] = {
        key: blobs[key] for key in sorted(blobs)
    }
    freeze_path.write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def import_packages(
    *,
    package_root: Path,
    evidence_root: Path,
    request_path: Path,
) -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if set(request.get("requested_review_ids") or []) != EXPECTED_REVIEW_IDS:
        raise Day14ImportError("The Day 14 request has an unexpected target set")
    if set(request.get("replacement_review_ids") or []) != EXPECTED_REPLACEMENTS:
        raise Day14ImportError("The Day 14 replacement set is invalid")
    if set(request.get("addition_review_ids") or []) != EXPECTED_ADDITIONS:
        raise Day14ImportError("The Day 14 addition set is invalid")
    safety = request.get("safety") or {}
    if any(
        safety.get(key) is not False
        for key in (
            "allow_real_application_submit",
            "autopilot_enabled",
            "captcha_bypass_allowed",
            "final_submit_clicked",
            "maturity_promotion_allowed",
            "resumable_handoffs_enabled",
            "supervised_pilot_enabled",
        )
    ) or safety.get("synthetic_profiles_only") is not True:
        raise Day14ImportError("The Day 14 request weakens a safety boundary")

    incoming = package_root / "evidence"
    if not incoming.is_dir():
        raise Day14ImportError(f"Missing package evidence root: {incoming}")
    candidate_paths = sorted(incoming.glob("lever-phase-a-candidate-D8-*.csv"))
    incoming_ids = {
        path.stem.removeprefix("lever-phase-a-candidate-")
        for path in candidate_paths
    }
    if incoming_ids != EXPECTED_REVIEW_IDS or len(candidate_paths) != 10:
        raise Day14ImportError(
            f"Expected all ten finalized packages, found {sorted(incoming_ids)}"
        )

    baseline_path = evidence_root / "lever-phase-a-baseline.csv"
    sources_path = evidence_root / "lever-phase-a-sources.csv"
    baseline_fields, baseline_rows = _read_rows(baseline_path)
    source_fields, source_rows = _read_rows(sources_path)
    existing_by_identity: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for row in baseline_rows:
        identity = _identity(row)
        if identity in existing_by_identity:
            raise Day14ImportError(f"Existing duplicate target identity: {identity}")
        existing_by_identity[identity] = row

    candidates: Dict[str, Dict[str, str]] = {}
    incoming_sources: Dict[str, Dict[str, str]] = {}
    replacements: List[Dict[str, Any]] = []
    additions: List[Dict[str, Any]] = []
    old_source_keys: set[Tuple[str, str]] = set()

    for candidate_path in candidate_paths:
        review_id = candidate_path.stem.removeprefix("lever-phase-a-candidate-")
        candidate = _load_one_row(candidate_path, baseline_fields)
        source_path = incoming / f"lever-phase-a-source-{review_id}.csv"
        source = _load_one_row(source_path, source_fields)
        _validate_source(source)

        if _review_id_from_artifact_path(candidate.get("artifact_path")) != review_id:
            raise Day14ImportError(f"Candidate artifact path mismatch for {review_id}")
        if candidate.get("pre_submit_state") != "ready_to_submit":
            raise Day14ImportError(f"Candidate {review_id} is not ready_to_submit")
        if candidate.get("final_status") != "dry_run_passed":
            raise Day14ImportError(f"Candidate {review_id} did not dry-run pass")
        if str(candidate.get("source_reference") or "").rstrip("/").split("/")[-1] != (
            source["workflow_run_id"]
        ):
            raise Day14ImportError(f"Source reference mismatch for {review_id}")

        report_path = incoming / Path(str(candidate["artifact_path"]))
        if not report_path.is_file():
            raise Day14ImportError(f"Missing retained report for {review_id}")
        if _sha256(report_path) != candidate["artifact_sha256"]:
            raise Day14ImportError(f"Report digest mismatch for {review_id}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        target = load_locked_target(
            review_id,
            evidence_root / "lever-phase-a-target-corpus",
        )
        validate_ready_report(report, target)

        archive_path = _source_archive_path(incoming, review_id, source)
        if not archive_path.is_file():
            raise Day14ImportError(f"Missing finalized archive for {review_id}")
        if _sha256(archive_path) != source["artifact_digest"]:
            raise Day14ImportError(f"Archive digest mismatch for {review_id}")

        identity = _identity(candidate)
        expected_target = (
            str(target["region"]).lower(),
            str(target["site"]).lower(),
            str(target["posting_id"]).lower(),
        )
        if identity != expected_target:
            raise Day14ImportError(f"Frozen identity mismatch for {review_id}")
        candidates[review_id] = candidate
        incoming_sources[review_id] = source

        old_row = existing_by_identity.get(identity)
        if review_id in EXPECTED_REPLACEMENTS:
            if old_row is None:
                raise Day14ImportError(f"Missing canonical row to replace for {review_id}")
            if _review_id_from_artifact_path(old_row.get("artifact_path")) != review_id:
                raise Day14ImportError(f"Replacement review ID mismatch for {review_id}")
            old_source_path = evidence_root / f"lever-phase-a-source-{review_id}.csv"
            old_source = _load_one_row(old_source_path, source_fields)
            _validate_source(old_source)
            if old_source not in source_rows:
                raise Day14ImportError(f"Old source receipt is not canonical for {review_id}")
            old_archive = _source_archive_path(evidence_root, review_id, old_source)
            if not old_archive.is_file():
                raise Day14ImportError(f"Historical archive missing for {review_id}")
            if _sha256(old_archive) != old_source["artifact_digest"]:
                raise Day14ImportError(f"Historical archive digest mismatch for {review_id}")
            old_source_keys.add(_source_key(old_source))
            replacements.append({
                "review_id": review_id,
                "target": {
                    "region": identity[0],
                    "site": identity[1],
                    "posting_id": identity[2],
                },
                "superseded": {
                    "record": old_row,
                    "source": old_source,
                    "archive_path": old_archive.relative_to(evidence_root).as_posix(),
                },
                "superseding": {
                    "record": candidate,
                    "source": source,
                },
            })
        else:
            if review_id not in EXPECTED_ADDITIONS or old_row is not None:
                raise Day14ImportError(f"Unexpected addition identity for {review_id}")
            additions.append({
                "review_id": review_id,
                "target": {
                    "region": identity[0],
                    "site": identity[1],
                    "posting_id": identity[2],
                },
                "record": candidate,
                "source": source,
            })

    if {item["review_id"] for item in replacements} != EXPECTED_REPLACEMENTS:
        raise Day14ImportError("The replacement ledger is incomplete")
    if {item["review_id"] for item in additions} != EXPECTED_ADDITIONS:
        raise Day14ImportError("The addition ledger is incomplete")

    staged = evidence_root.parent / ".lever-day14-staged-evidence"
    shutil.rmtree(staged, ignore_errors=True)
    shutil.copytree(evidence_root, staged)
    shutil.copytree(incoming, staged, dirs_exist_ok=True)

    replacement_by_identity = {
        _identity(candidates[review_id]): candidates[review_id]
        for review_id in EXPECTED_REPLACEMENTS
    }
    new_baseline_rows: List[Dict[str, str]] = []
    for row in baseline_rows:
        replacement = replacement_by_identity.get(_identity(row))
        new_baseline_rows.append(replacement if replacement is not None else row)
    new_baseline_rows.extend(
        candidates[review_id] for review_id in sorted(EXPECTED_ADDITIONS)
    )

    new_source_rows = [
        row for row in source_rows if _source_key(row) not in old_source_keys
    ]
    new_source_rows.extend(
        incoming_sources[review_id] for review_id in sorted(EXPECTED_REVIEW_IDS)
    )
    if len({_source_key(row) for row in new_source_rows}) != len(new_source_rows):
        raise Day14ImportError("The final source manifest contains duplicates")

    _write_rows(staged / baseline_path.name, baseline_fields, new_baseline_rows)
    _write_rows(staged / sources_path.name, source_fields, new_source_rows)

    supersession = {
        "schema_version": "1.0",
        "reason": "stronger_serialized_control_evidence",
        "replacements": sorted(replacements, key=lambda item: item["review_id"]),
        "additions": sorted(additions, key=lambda item: item["review_id"]),
        "safety": {
            "final_submit_clicked": False,
            "historical_archives_preserved": True,
            "quota_credit_counted_once": True,
            "replacement_count": 8,
            "addition_count": 2,
        },
    }
    (staged / "lever-phase-a-day14-supersessions.json").write_text(
        json.dumps(supersession, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    loaded = load_phase_a_baseline(staged / baseline_path.name)
    readiness = read_lever_pilot_readiness(
        baseline_path=staged / baseline_path.name,
        ledger_path=staged / ".missing-phase-b-runtime.jsonl",
    )
    summary = readiness["summary"]
    if readiness["baseline_record_count"] != 31:
        raise Day14ImportError("The final baseline must contain 31 records")
    if summary["qualifying_dry_run_count"] != 30:
        raise Day14ImportError("The final checkpoint did not reach 30 qualifiers")
    if summary["distinct_site_count"] != 30:
        raise Day14ImportError("The final checkpoint did not reach 30 distinct sites")
    if summary["manual_challenge_boundary_count"] != 1:
        raise Day14ImportError("The final checkpoint lost its challenge boundary")
    if summary["phase_a_external_archive_failure_count"] != 0:
        raise Day14ImportError("The final checkpoint has an archive failure")
    if summary["phase_a_inspection_failure_count"] != 0:
        raise Day14ImportError("The final checkpoint has an inspection failure")
    if summary["duplicate_submission_count"] != 0:
        raise Day14ImportError("The final checkpoint introduced a duplicate submission")
    if summary["false_submitted_count"] != 0:
        raise Day14ImportError("The final checkpoint introduced a false submission")
    if summary["canonical_maturity"] != "dry_run":
        raise Day14ImportError("The final checkpoint changed canonical maturity")
    if summary["promotion_ready"] is not False:
        raise Day14ImportError("The final checkpoint enabled promotion")
    if any(record.get("final_submit_clicked") for record in loaded):
        raise Day14ImportError("The final checkpoint recorded a submit click")
    if len(new_source_rows) != 32:
        raise Day14ImportError("The final source manifest must contain 32 receipts")

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
        "requested_review_ids": sorted(EXPECTED_REVIEW_IDS),
        "replacement_review_ids": sorted(EXPECTED_REPLACEMENTS),
        "addition_review_ids": sorted(EXPECTED_ADDITIONS),
        "qualifying_count_before": 28,
        "qualifying_count_added": 2,
        "qualifying_count_after": 30,
        "distinct_site_count_after": 30,
        "baseline_record_count_after": 31,
        "source_receipt_count_after": 32,
        "regions_covered": summary["regions_covered"],
        "safety": {
            "final_submit_clicked": False,
            "captcha_bypassed": False,
            "duplicate_submission_count": 0,
            "false_submitted_count": 0,
            "external_archive_failure_count": 0,
            "maturity_promoted": False,
            "real_submission_enabled": False,
        },
    }
    (staged / "lever-phase-a-day14-2026-08-04.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    shutil.copytree(staged, evidence_root, dirs_exist_ok=True)
    shutil.rmtree(staged)
    _write_day14_verifier(root)
    _refresh_freeze(root)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--evidence-root", default=Path("evidence"), type=Path)
    parser.add_argument(
        "--request",
        default=Path("evidence/lever-phase-a-day14-request.json"),
        type=Path,
    )
    args = parser.parse_args()
    result = import_packages(
        package_root=args.package_root,
        evidence_root=args.evidence_root,
        request_path=args.request,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
