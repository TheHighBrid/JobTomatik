"""External provenance contract for interactive Lever Phase A evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Sequence

import httpx

from app.services.ats_lever import LEVER_ADAPTER_VERSION, parse_lever_job_url
from app.services.lever_phase_a_operator import (
    frozen_target_identity,
    load_locked_target,
)
from app.services.lever_pilot_ingestion import load_phase_a_baseline
from scripts.export_lever_phase_a_record import (
    build_phase_a_candidate,
    export_phase_a_candidate,
)


REPOSITORY = "TheHighBrid/JobTomatik"
GITHUB_API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
ACTIONS_RUN_PREFIX = f"https://github.com/{REPOSITORY}/actions/runs/"
SOURCE_FIELDNAMES = [
    "workflow_run_id",
    "artifact_id",
    "artifact_digest",
    "retained_record_count",
]
_REPORT_NAME = "lever-phase-a-interactive-report.json"
_MANIFEST_NAME = "lever-phase-a-interactive-retention-manifest.json"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DIGITS = re.compile(r"[1-9][0-9]*")


class LeverPhaseAProvenanceError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _same_url(left: Any, right: Any) -> bool:
    return str(left or "").strip().rstrip("/") == str(right or "").strip().rstrip("/")


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def validate_external_provenance(
    *,
    workflow_run_id: str,
    artifact_id: str,
    artifact_digest: str,
) -> Dict[str, str]:
    run_id = str(workflow_run_id or "").strip()
    retained_artifact_id = str(artifact_id or "").strip()
    digest = str(artifact_digest or "").strip()
    if not _DIGITS.fullmatch(run_id):
        raise LeverPhaseAProvenanceError(
            "workflow_run_id must be a positive numeric GitHub Actions run ID"
        )
    if not _DIGITS.fullmatch(retained_artifact_id):
        raise LeverPhaseAProvenanceError(
            "artifact_id must be a positive numeric GitHub Actions artifact ID"
        )
    if not _HEX64.fullmatch(digest):
        raise LeverPhaseAProvenanceError(
            "artifact_digest must be a lowercase 64-character SHA-256 digest"
        )
    return {
        "workflow_run_id": run_id,
        "artifact_id": retained_artifact_id,
        "artifact_digest": digest,
        "source_reference": ACTIONS_RUN_PREFIX + run_id,
    }


def require_retained_report_path(report_path: Path, evidence_root: Path) -> str:
    report = Path(report_path).resolve()
    root = Path(evidence_root).resolve()
    artifacts_root = (root / "lever-phase-a-artifacts").resolve()
    try:
        relative = report.relative_to(artifacts_root)
    except ValueError as exc:
        raise LeverPhaseAProvenanceError(
            "The report must be retained below evidence/lever-phase-a-artifacts"
        ) from exc
    if len(relative.parts) != 2 or relative.name != _REPORT_NAME:
        raise LeverPhaseAProvenanceError(
            "The report path must be lever-phase-a-artifacts/<REVIEW_ID>/"
            + _REPORT_NAME
        )
    return report.relative_to(root).as_posix()


def _matching_interactive_records(
    report: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if report.get("certification") != "lever_supervised_live_dry_run":
        raise LeverPhaseAProvenanceError(
            "The retained report is not a Lever supervised live dry run"
        )
    if report.get("interactive_handoff") is not True:
        raise LeverPhaseAProvenanceError(
            "The retained report is not marked as an interactive handoff"
        )
    if report.get("passed") is not True or report.get("final_submit_clicked") is not False:
        raise LeverPhaseAProvenanceError(
            "The retained interactive report did not pass without submission"
        )
    records = [item for item in report.get("reports") or [] if isinstance(item, Mapping)]
    inspections = [item for item in records if item.get("mode") == "inspect"]
    exercises = [item for item in records if item.get("mode") == "exercise"]
    if len(inspections) != 1 or len(exercises) != 1:
        raise LeverPhaseAProvenanceError(
            "Exactly one inspection and one interactive exercise are required"
        )
    inspection = inspections[0]
    exercise = exercises[0]
    if exercise.get("certification_outcome") != "ready_to_submit":
        raise LeverPhaseAProvenanceError(
            "The retained interactive exercise did not reach ready_to_submit"
        )
    verification = dict(exercise.get("handoff_verification") or {})
    if (
        verification.get("challenge_cleared") is not True
        or verification.get("target_verification", {}).get("verified") is not True
    ):
        raise LeverPhaseAProvenanceError(
            "The retained interactive handoff was not independently verified"
        )
    if exercise.get("submit_guard") != {
        "installed": True,
        "blocked_clicks": 0,
        "blocked_submits": 0,
    }:
        raise LeverPhaseAProvenanceError(
            "The retained interactive submit guard was not clean"
        )
    return inspection, exercise


def _require_locked_target_binding(
    report: Mapping[str, Any],
    target: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    inspection, exercise = _matching_interactive_records(report)
    expected_url = str(target.get("canonical_application_url") or "")
    if not _same_url(inspection.get("url"), expected_url) or not _same_url(
        exercise.get("url"), expected_url
    ):
        raise LeverPhaseAProvenanceError(
            "The retained report URLs do not match the frozen canonical application URL"
        )
    expected_identity = (
        str(target.get("site") or ""),
        str(target.get("posting_id") or ""),
        str(target.get("region") or "").lower(),
    )
    for observed_url in (inspection.get("url"), exercise.get("url")):
        if parse_lever_job_url(str(observed_url or "")) != expected_identity:
            raise LeverPhaseAProvenanceError(
                "The retained report URL target identity does not match the frozen target"
            )
    if (
        inspection.get("adapter") != "lever"
        or inspection.get("adapter_version") != LEVER_ADAPTER_VERSION
        or exercise.get("adapter") != "lever"
        or exercise.get("adapter_version") != LEVER_ADAPTER_VERSION
    ):
        raise LeverPhaseAProvenanceError(
            "The retained report does not use the certified Lever adapter version"
        )

    metadata = dict(exercise.get("certification_metadata") or {})
    if str(metadata.get("review_id") or "") != str(target.get("review_id") or ""):
        raise LeverPhaseAProvenanceError(
            "The retained report does not match the requested frozen review ID"
        )
    frozen = dict(metadata.get("frozen_target") or {})
    expected_frozen = frozen_target_identity(target)
    if frozen != expected_frozen:
        raise LeverPhaseAProvenanceError(
            "The retained frozen-target identity does not match the locked corpus row"
        )
    supervised = dict(metadata.get("supervised_target") or {})
    expected_supervised = {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": LEVER_ADAPTER_VERSION,
        "site": expected_identity[0],
        "posting_id": expected_identity[1],
        "region": expected_identity[2],
        "canonical_application_url": expected_url,
    }
    for key, expected in expected_supervised.items():
        observed = supervised.get(key)
        matches = _same_url(observed, expected) if key == "canonical_application_url" else (
            str(observed or "") == str(expected)
        )
        if not matches:
            raise LeverPhaseAProvenanceError(
                f"The retained supervised target does not match frozen field {key}"
            )
    if _normalized_text(supervised.get("official_title")) != _normalized_text(
        target.get("role")
    ):
        raise LeverPhaseAProvenanceError(
            "The retained official title does not match the frozen role"
        )
    return inspection, exercise


def _safe_archive_members(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for raw_name in archive.namelist():
        path = PurePosixPath(raw_name)
        if path.is_absolute() or ".." in path.parts:
            raise LeverPhaseAProvenanceError(
                "The retained artifact archive contains an unsafe path"
            )
        if not raw_name.endswith("/"):
            names.append(path.as_posix())
    return names


def verify_retention_artifact_bundle(
    *,
    artifact_metadata: Mapping[str, Any],
    archive_bytes: bytes,
    local_report_path: Path,
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
    if str(artifact_metadata.get("id") or "") != provenance["artifact_id"]:
        raise LeverPhaseAProvenanceError("GitHub returned a different artifact ID")
    if artifact_metadata.get("expired") is not False:
        raise LeverPhaseAProvenanceError("The GitHub Actions artifact has expired")
    workflow = dict(artifact_metadata.get("workflow_run") or {})
    if str(workflow.get("id") or "") != provenance["workflow_run_id"]:
        raise LeverPhaseAProvenanceError(
            "The GitHub artifact does not belong to the claimed workflow run"
        )
    expected_name_prefix = f"lever-phase-a-interactive-{review_id}-"
    if not str(artifact_metadata.get("name") or "").startswith(expected_name_prefix):
        raise LeverPhaseAProvenanceError(
            "The GitHub artifact name does not match the frozen review ID"
        )
    if str(artifact_metadata.get("digest") or "") != (
        "sha256:" + provenance["artifact_digest"]
    ):
        raise LeverPhaseAProvenanceError(
            "The official GitHub artifact digest does not match the supplied digest"
        )
    if _sha256_bytes(archive_bytes) != provenance["artifact_digest"]:
        raise LeverPhaseAProvenanceError(
            "The downloaded GitHub artifact archive digest does not match"
        )

    artifact_path = require_retained_report_path(local_report_path, evidence_root)
    local_report_bytes = Path(local_report_path).read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = _safe_archive_members(archive)
            report_names = [name for name in names if name.endswith(artifact_path)]
            manifest_names = [name for name in names if name.endswith(_MANIFEST_NAME)]
            if len(report_names) != 1 or len(manifest_names) != 1:
                raise LeverPhaseAProvenanceError(
                    "The GitHub artifact must contain one retained report and one manifest"
                )
            artifact_report_bytes = archive.read(report_names[0])
            manifest = json.loads(archive.read(manifest_names[0]).decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeverPhaseAProvenanceError(
            f"The retained GitHub artifact is invalid: {exc}"
        ) from exc

    if artifact_report_bytes != local_report_bytes:
        raise LeverPhaseAProvenanceError(
            "The local report is not byte-identical to the externally retained report"
        )
    report_digest = _sha256_bytes(artifact_report_bytes)
    manifest_report = dict(manifest.get("report") or {})
    if (
        manifest.get("repository") != REPOSITORY
        or str(manifest.get("workflow_run_id") or "") != provenance["workflow_run_id"]
        or manifest.get("retained_record_count") != 1
        or manifest_report.get("review_id") != review_id
        or manifest_report.get("path") != artifact_path
        or manifest_report.get("sha256") != report_digest
    ):
        raise LeverPhaseAProvenanceError(
            "The retained artifact manifest does not bind the claimed report and run"
        )
    try:
        report = json.loads(artifact_report_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeverPhaseAProvenanceError(
            f"The externally retained report is not valid JSON: {exc}"
        ) from exc
    if not isinstance(report, dict):
        raise LeverPhaseAProvenanceError(
            "The externally retained report must be a JSON object"
        )
    return {
        "report": report,
        "report_sha256": report_digest,
        "archive_bytes": archive_bytes,
        "archive_sha256": provenance["artifact_digest"],
        "artifact_path": artifact_path,
        "manifest": manifest,
        "provenance": provenance,
    }


def fetch_verified_retention_artifact(
    *,
    github_token: str,
    local_report_path: Path,
    evidence_root: Path,
    review_id: str,
    workflow_run_id: str,
    artifact_id: str,
    artifact_digest: str,
) -> Dict[str, Any]:
    if not str(github_token or "").strip():
        raise LeverPhaseAProvenanceError(
            "A GitHub token is required to verify and download the retained artifact"
        )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=60.0) as client:
            metadata_response = client.get(
                f"{GITHUB_API_ROOT}/actions/artifacts/{artifact_id}"
            )
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            archive_response = client.get(
                f"{GITHUB_API_ROOT}/actions/artifacts/{artifact_id}/zip"
            )
            archive_response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise LeverPhaseAProvenanceError(
            f"GitHub artifact verification failed: {type(exc).__name__}"
        ) from exc
    if not isinstance(metadata, dict):
        raise LeverPhaseAProvenanceError(
            "GitHub artifact metadata did not return an object"
        )
    return verify_retention_artifact_bundle(
        artifact_metadata=metadata,
        archive_bytes=archive_response.content,
        local_report_path=local_report_path,
        evidence_root=evidence_root,
        review_id=review_id,
        workflow_run_id=workflow_run_id,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )


def write_source_receipt(
    output_path: Path,
    provenance: Mapping[str, str],
) -> None:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {
                "workflow_run_id": provenance["workflow_run_id"],
                "artifact_id": provenance["artifact_id"],
                "artifact_digest": provenance["artifact_digest"],
                "retained_record_count": 1,
            }
        )


def _write_temp(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.finalizing")
    temporary.unlink(missing_ok=True)
    temporary.write_bytes(data)
    return temporary


def _restore_output(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    rollback = path.with_name(f".{path.name}.rollback")
    rollback.write_bytes(previous)
    os.replace(rollback, path)


def _publish_outputs_with_rollback(
    publications: Sequence[tuple[Path, Path]],
) -> None:
    previous: Dict[Path, bytes | None] = {}
    for _, target in publications:
        if target.exists() and not target.is_file():
            raise LeverPhaseAProvenanceError(
                f"Finalization output is not a regular file: {target}"
            )
        previous[target] = target.read_bytes() if target.is_file() else None
    try:
        for temporary, target in publications:
            os.replace(temporary, target)
    except Exception:
        rollback_errors: list[str] = []
        for _, target in reversed(publications):
            try:
                _restore_output(target, previous[target])
            except Exception as exc:
                rollback_errors.append(f"{target}: {type(exc).__name__}")
        if rollback_errors:
            raise LeverPhaseAProvenanceError(
                "Finalization failed and rollback was incomplete: "
                + ", ".join(rollback_errors)
            )
        raise
    finally:
        for temporary, _ in publications:
            temporary.unlink(missing_ok=True)
        for _, target in publications:
            target.with_name(f".{target.name}.rollback").unlink(missing_ok=True)


def finalize_interactive_candidate(
    *,
    report_path: Path,
    review_id: str,
    corpus_root: Path,
    evidence_root: Path,
    candidate_path: Path,
    source_receipt_path: Path,
    operator: str,
    workflow_run_id: str,
    artifact_id: str,
    artifact_digest: str,
    github_token: str,
    run_id: str | None = None,
) -> Dict[str, Any]:
    target = load_locked_target(review_id, corpus_root)
    retained = fetch_verified_retention_artifact(
        github_token=github_token,
        local_report_path=Path(report_path),
        evidence_root=Path(evidence_root),
        review_id=str(target["review_id"]),
        workflow_run_id=workflow_run_id,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )
    report = dict(retained["report"])
    _require_locked_target_binding(report, target)
    provenance = dict(retained["provenance"])
    final_run_id = str(run_id or "").strip() or (
        f"github-actions-{provenance['workflow_run_id']}-interactive-"
        f"{str(target['review_id']).lower()}"
    )
    candidate = Path(candidate_path)
    source_receipt = Path(source_receipt_path)
    archive = (
        Path(evidence_root)
        / "lever-phase-a-external-archives"
        / str(target["review_id"])
        / f"artifact-{provenance['artifact_id']}-{provenance['artifact_digest']}.zip"
    )
    record = build_phase_a_candidate(
        report,
        report_path=Path(report_path),
        output_path=candidate,
        artifact_path=str(retained["artifact_path"]),
        run_id=final_run_id,
        operator=operator,
        source_reference=provenance["source_reference"],
        employer=str(target["employer"]),
        role=str(target["role"]),
    )

    candidate_temp = candidate.with_name(f".{candidate.name}.finalizing")
    source_temp = source_receipt.with_name(f".{source_receipt.name}.finalizing")
    archive_temp = _write_temp(archive, retained["archive_bytes"])
    try:
        export_phase_a_candidate(candidate_temp, record)
        loaded = load_phase_a_baseline(candidate_temp)
        if len(loaded) != 1 or loaded[0].get("qualifies_for_dry_run_matrix") is not True:
            raise LeverPhaseAProvenanceError(
                "The externally retained interactive candidate did not qualify"
            )
        write_source_receipt(source_temp, provenance)
        _publish_outputs_with_rollback(
            (
                (candidate_temp, candidate),
                (source_temp, source_receipt),
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


__all__ = [
    "ACTIONS_RUN_PREFIX",
    "LeverPhaseAProvenanceError",
    "SOURCE_FIELDNAMES",
    "fetch_verified_retention_artifact",
    "finalize_interactive_candidate",
    "require_retained_report_path",
    "validate_external_provenance",
    "verify_retention_artifact_bundle",
    "write_source_receipt",
]
