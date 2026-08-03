#!/usr/bin/env python3
"""Validate and finalize one externally retained ordinary Lever Phase A dry run."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Sequence

from app.services.ats_lever import LEVER_ADAPTER_VERSION, parse_lever_job_url
from app.services.lever_phase_a_operator import load_locked_target
from app.services.lever_phase_a_provenance import (
    LeverPhaseAProvenanceError,
    validate_external_provenance,
    write_source_receipt,
)
from app.services.lever_pilot_ingestion import load_phase_a_baseline
from scripts.export_lever_phase_a_record import (
    build_phase_a_candidate,
    export_phase_a_candidate,
)


REPORT_NAME = "lever-phase-a-report.json"
MANIFEST_NAME = "lever-phase-a-ready-retention-manifest.json"
ARTIFACT_PREFIX = "lever-phase-a-ready-"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _same_url(left: Any, right: Any) -> bool:
    return str(left or "").strip().rstrip("/") == str(right or "").strip().rstrip("/")


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _load_report(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeverPhaseAProvenanceError(f"The retained report is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise LeverPhaseAProvenanceError("The retained report must be a JSON object")
    return value


def require_report_path(report_path: Path, evidence_root: Path) -> str:
    report = Path(report_path).resolve()
    root = Path(evidence_root).resolve()
    artifacts = (root / "lever-phase-a-artifacts").resolve()
    try:
        relative = report.relative_to(artifacts)
    except ValueError as exc:
        raise LeverPhaseAProvenanceError(
            "The report must be retained below evidence/lever-phase-a-artifacts"
        ) from exc
    if len(relative.parts) != 2 or relative.name != REPORT_NAME:
        raise LeverPhaseAProvenanceError(
            "The report path must be lever-phase-a-artifacts/<REVIEW_ID>/" + REPORT_NAME
        )
    return report.relative_to(root).as_posix()


def validate_ready_report(
    report: Mapping[str, Any],
    target: Mapping[str, Any],
) -> Dict[str, Any]:
    if report.get("certification") != "lever_supervised_live_dry_run":
        raise LeverPhaseAProvenanceError("The report is not a Lever supervised live dry run")
    if report.get("interactive_handoff") is True:
        raise LeverPhaseAProvenanceError(
            "Interactive reports must use the interactive retention workflow"
        )
    if report.get("passed") is not True or report.get("final_submit_clicked") is not False:
        raise LeverPhaseAProvenanceError("The report did not pass without submission")

    items = [item for item in report.get("reports") or [] if isinstance(item, Mapping)]
    inspections = [item for item in items if item.get("mode") == "inspect"]
    exercises = [item for item in items if item.get("mode") == "exercise"]
    if len(inspections) != 1 or len(exercises) != 1:
        raise LeverPhaseAProvenanceError(
            "Exactly one inspection and one dry-run exercise are required"
        )
    inspection = inspections[0]
    exercise = exercises[0]

    expected_url = str(target.get("canonical_application_url") or "")
    expected_identity = (
        str(target.get("site") or ""),
        str(target.get("posting_id") or ""),
        str(target.get("region") or "").lower(),
    )
    for observed in (inspection.get("url"), exercise.get("url")):
        if not _same_url(observed, expected_url):
            raise LeverPhaseAProvenanceError(
                "The retained report URL does not match the frozen target"
            )
        if parse_lever_job_url(str(observed or "")) != expected_identity:
            raise LeverPhaseAProvenanceError(
                "The retained target identity does not match the frozen corpus row"
            )

    if inspection.get("passed") is not True:
        raise LeverPhaseAProvenanceError("The official posting inspection did not pass")
    if inspection.get("posting_available") is not True:
        raise LeverPhaseAProvenanceError("The frozen posting was unavailable")
    if inspection.get("posting_http_status") != 200:
        raise LeverPhaseAProvenanceError("The official posting did not return HTTP 200")
    if inspection.get("final_submit_clicked") is not False:
        raise LeverPhaseAProvenanceError("The inspection recorded a submit action")
    if inspection.get("adapter") != "lever" or (
        inspection.get("adapter_version") != LEVER_ADAPTER_VERSION
    ):
        raise LeverPhaseAProvenanceError(
            "The inspection does not use the certified Lever adapter version"
        )
    posting = dict(inspection.get("posting_metadata") or {})
    if posting.get("posting_metadata_certified") is not True:
        raise LeverPhaseAProvenanceError("Official posting metadata was not certified")
    if posting.get("apply_url_matches_posting") is not True:
        raise LeverPhaseAProvenanceError("The hosted apply URL does not match the posting")
    if _normalized(posting.get("title")) != _normalized(target.get("role")):
        raise LeverPhaseAProvenanceError(
            "The official title does not match the frozen role"
        )

    if exercise.get("passed") is not True:
        raise LeverPhaseAProvenanceError("The dry-run exercise did not pass")
    if exercise.get("certification_outcome") != "ready_to_submit":
        raise LeverPhaseAProvenanceError("The exercise did not reach ready_to_submit")
    if exercise.get("ready_to_submit") is not True:
        raise LeverPhaseAProvenanceError("The exercise is not ready to submit")
    if exercise.get("requires_manual_review") is not False:
        raise LeverPhaseAProvenanceError("The exercise still requires manual review")
    if exercise.get("final_submit_clicked") is not False:
        raise LeverPhaseAProvenanceError("The exercise recorded a final submit action")
    if exercise.get("review_items") or exercise.get("validation_errors"):
        raise LeverPhaseAProvenanceError("The exercise contains unresolved blockers")
    if exercise.get("error") not in (None, ""):
        raise LeverPhaseAProvenanceError("The exercise retained an error")
    if int(exercise.get("fields_filled") or 0) <= 0:
        raise LeverPhaseAProvenanceError("The exercise did not fill any fields")
    if int(exercise.get("control_evidence_count") or 0) <= 0:
        raise LeverPhaseAProvenanceError("The exercise lacks control evidence")
    if not any(
        item.get("verification") == "passed"
        for item in exercise.get("upload_evidence") or []
    ):
        raise LeverPhaseAProvenanceError("The resume upload was not verified")
    if exercise.get("adapter") != "lever" or (
        exercise.get("adapter_version") != LEVER_ADAPTER_VERSION
    ):
        raise LeverPhaseAProvenanceError(
            "The exercise does not use the certified Lever adapter version"
        )

    metadata = dict(exercise.get("certification_metadata") or {})
    if metadata.get("synthetic_profile") is not True:
        raise LeverPhaseAProvenanceError("The exercise was not synthetic-only")
    for key, expected in zip(("site", "posting_id", "region"), expected_identity):
        if str(metadata.get(key) or "").lower() != str(expected).lower():
            raise LeverPhaseAProvenanceError(
                f"Certification metadata does not match frozen field {key}"
            )

    return {
        "review_id": str(target.get("review_id") or ""),
        "inspection": inspection,
        "exercise": exercise,
    }


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for raw in archive.namelist():
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            raise LeverPhaseAProvenanceError("The artifact contains an unsafe path")
        if not raw.endswith("/"):
            names.append(path.as_posix())
    return names


def verify_artifact_bundle(
    *,
    metadata: Mapping[str, Any],
    archive_bytes: bytes,
    report_path: Path,
    evidence_root: Path,
    review_id: str,
    workflow_run_id: str,
    artifact_id: str,
    artifact_digest: str,
) -> Dict[str, Any]:
    provenance = validate_external_provenance(
        workflow_run_id=workflow_run_id,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )
    if str(metadata.get("id") or "") != provenance["artifact_id"]:
        raise LeverPhaseAProvenanceError("GitHub returned a different artifact ID")
    if metadata.get("expired") is not False:
        raise LeverPhaseAProvenanceError("The GitHub artifact has expired")
    if str((metadata.get("workflow_run") or {}).get("id") or "") != (
        provenance["workflow_run_id"]
    ):
        raise LeverPhaseAProvenanceError("The artifact belongs to a different workflow run")
    if not str(metadata.get("name") or "").startswith(
        f"{ARTIFACT_PREFIX}{review_id}-"
    ):
        raise LeverPhaseAProvenanceError("The artifact name does not match the review ID")
    if str(metadata.get("digest") or "") != "sha256:" + provenance["artifact_digest"]:
        raise LeverPhaseAProvenanceError("The official artifact digest does not match")
    if _sha256(archive_bytes) != provenance["artifact_digest"]:
        raise LeverPhaseAProvenanceError("The downloaded artifact ZIP digest does not match")

    artifact_path = require_report_path(report_path, evidence_root)
    local_report = Path(report_path).read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = _safe_members(archive)
            reports = [name for name in names if name.endswith(artifact_path)]
            manifests = [name for name in names if name.endswith(MANIFEST_NAME)]
            if len(reports) != 1 or len(manifests) != 1:
                raise LeverPhaseAProvenanceError(
                    "The artifact must contain one report and one retention manifest"
                )
            retained_report = archive.read(reports[0])
            manifest = json.loads(archive.read(manifests[0]).decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeverPhaseAProvenanceError(f"The retained artifact is invalid: {exc}") from exc

    if retained_report != local_report:
        raise LeverPhaseAProvenanceError(
            "The local report is not byte-identical to the retained report"
        )
    report_sha = _sha256(retained_report)
    manifest_report = dict(manifest.get("report") or {})
    if (
        manifest.get("repository") != "TheHighBrid/JobTomatik"
        or str(manifest.get("workflow_run_id") or "") != provenance["workflow_run_id"]
        or manifest.get("retained_record_count") != 1
        or manifest_report.get("review_id") != review_id
        or manifest_report.get("path") != artifact_path
        or manifest_report.get("sha256") != report_sha
    ):
        raise LeverPhaseAProvenanceError(
            "The retention manifest does not bind the claimed report and run"
        )

    report = _load_report(Path(report_path))
    return {
        "report": report,
        "report_sha256": report_sha,
        "archive_sha256": provenance["artifact_digest"],
        "artifact_path": artifact_path,
        "provenance": provenance,
    }


def _write_temp(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.finalizing")
    temporary.unlink(missing_ok=True)
    temporary.write_bytes(data)
    return temporary


def _restore(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    rollback = path.with_name(f".{path.name}.rollback")
    rollback.write_bytes(previous)
    os.replace(rollback, path)


def _publish(publications: Sequence[tuple[Path, Path]]) -> None:
    previous = {
        target: target.read_bytes() if target.is_file() else None
        for _, target in publications
    }
    try:
        for temporary, target in publications:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, target)
    except Exception:
        for _, target in reversed(publications):
            _restore(target, previous[target])
        raise
    finally:
        for temporary, _ in publications:
            temporary.unlink(missing_ok=True)
        for _, target in publications:
            target.with_name(f".{target.name}.rollback").unlink(missing_ok=True)


def finalize(args: argparse.Namespace) -> Dict[str, Any]:
    evidence_root = Path(args.evidence_root)
    corpus_root = Path(args.corpus_root)
    report_path = Path(args.report)
    target = load_locked_target(args.review_id, corpus_root)
    report = _load_report(report_path)
    validate_ready_report(report, target)

    metadata = _load_report(Path(args.artifact_metadata))
    archive_bytes = Path(args.artifact_zip).read_bytes()
    retained = verify_artifact_bundle(
        metadata=metadata,
        archive_bytes=archive_bytes,
        report_path=report_path,
        evidence_root=evidence_root,
        review_id=str(target["review_id"]),
        workflow_run_id=args.workflow_run_id,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
    )
    provenance = dict(retained["provenance"])
    candidate = Path(args.candidate_output) if args.candidate_output else (
        evidence_root / f"lever-phase-a-candidate-{args.review_id}.csv"
    )
    source = Path(args.source_output) if args.source_output else (
        evidence_root / f"lever-phase-a-source-{args.review_id}.csv"
    )
    archive = (
        evidence_root
        / "lever-phase-a-external-archives"
        / args.review_id
        / f"artifact-{args.artifact_id}-{args.artifact_digest}.zip"
    )
    run_id = args.run_id or (
        f"github-actions-{args.workflow_run_id}-ready-{args.review_id.lower()}"
    )
    record = build_phase_a_candidate(
        report,
        report_path=report_path,
        output_path=candidate,
        artifact_path=str(retained["artifact_path"]),
        run_id=run_id,
        operator=args.operator,
        source_reference=provenance["source_reference"],
        employer=str(target["employer"]),
        role=str(target["role"]),
    )

    candidate_temp = candidate.with_name(f".{candidate.name}.finalizing")
    source_temp = source.with_name(f".{source.name}.finalizing")
    archive_temp = _write_temp(archive, archive_bytes)
    try:
        export_phase_a_candidate(candidate_temp, record)
        loaded = load_phase_a_baseline(candidate_temp)
        if len(loaded) != 1 or loaded[0].get("qualifies_for_dry_run_matrix") is not True:
            raise LeverPhaseAProvenanceError("The retained candidate did not qualify")
        write_source_receipt(source_temp, provenance)
        _publish(
            (
                (candidate_temp, candidate),
                (source_temp, source),
                (archive_temp, archive),
            )
        )
    finally:
        candidate_temp.unlink(missing_ok=True)
        source_temp.unlink(missing_ok=True)
        archive_temp.unlink(missing_ok=True)

    return {
        "candidate": record,
        "source_receipt": {
            "workflow_run_id": provenance["workflow_run_id"],
            "artifact_id": provenance["artifact_id"],
            "artifact_digest": provenance["artifact_digest"],
            "retained_record_count": 1,
        },
        "durable_archive": {
            "path": archive.as_posix(),
            "sha256": retained["archive_sha256"],
            "report_sha256": retained["report_sha256"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--artifact-metadata")
    parser.add_argument("--artifact-zip")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-digest")
    parser.add_argument("--operator")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--corpus-root", default="evidence/lever-phase-a-target-corpus"
    )
    parser.add_argument("--evidence-root", default="evidence")
    parser.add_argument("--candidate-output")
    parser.add_argument("--source-output")
    args = parser.parse_args()

    target = load_locked_target(args.review_id, Path(args.corpus_root))
    report = _load_report(Path(args.report))
    result = validate_ready_report(report, target)
    if args.validate_only:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    required = {
        "artifact_metadata": args.artifact_metadata,
        "artifact_zip": args.artifact_zip,
        "workflow_run_id": args.workflow_run_id,
        "artifact_id": args.artifact_id,
        "artifact_digest": args.artifact_digest,
        "operator": args.operator,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise SystemExit("Missing finalization arguments: " + ", ".join(missing))

    finalized = finalize(args)
    safe_summary = {
        "source_receipt": finalized.get("source_receipt"),
        "durable_archive": finalized.get("durable_archive"),
        "candidate_redacted": True,
    }
    print(json.dumps(safe_summary, indent=2, sort_keys=True, default=str))
    print("No row was appended to the canonical baseline or source manifest.")


if __name__ == "__main__":
    main()
