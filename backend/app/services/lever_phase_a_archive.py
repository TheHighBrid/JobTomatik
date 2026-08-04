"""Durable GitHub artifact archive verification for Lever Phase A rows."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping
from urllib.parse import urlparse


REPOSITORY = "TheHighBrid/JobTomatik"
SOURCE_MANIFEST_NAME = "lever-phase-a-sources.csv"
INTERACTIVE_RETENTION_MANIFEST_NAME = "lever-phase-a-interactive-retention-manifest.json"
READY_RETENTION_MANIFEST_NAME = "lever-phase-a-ready-retention-manifest.json"
RETENTION_MANIFEST_NAME = INTERACTIVE_RETENTION_MANIFEST_NAME
ARCHIVE_ROOT_NAME = "lever-phase-a-external-archives"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DIGITS = re.compile(r"[1-9][0-9]*")
_INTERACTIVE_RUN_ID = re.compile(
    r"github-actions-[1-9][0-9]*-interactive-d8-[0-9]{3}",
    re.IGNORECASE,
)
_READY_RUN_ID = re.compile(
    r"github-actions-[1-9][0-9]*-ready-d8-[0-9]{3}",
    re.IGNORECASE,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _actions_run_id(source_reference: Any) -> str:
    parsed = urlparse(str(source_reference or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 5 or parts[:4] != ["TheHighBrid", "JobTomatik", "actions", "runs"]:
        return ""
    return parts[4] if _DIGITS.fullmatch(parts[4]) else ""


def _retention_descriptor(artifact_path: Any) -> tuple[str, str, str]:
    path = PurePosixPath(str(artifact_path or "").strip())
    if (
        len(path.parts) != 3
        or path.parts[0] != "lever-phase-a-artifacts"
        or not re.fullmatch(r"D8-[0-9]{3}", path.parts[1])
    ):
        return "", "", ""
    if path.parts[2] == "lever-phase-a-interactive-report.json":
        return (
            path.parts[1],
            path.parts[2],
            INTERACTIVE_RETENTION_MANIFEST_NAME,
        )
    if path.parts[2] == "lever-phase-a-report.json":
        return path.parts[1], path.parts[2], READY_RETENTION_MANIFEST_NAME
    return "", "", ""


def _review_id_from_artifact_path(artifact_path: Any) -> str:
    return _retention_descriptor(artifact_path)[0]


def _normalized_manifest_report_path(value: Any) -> str:
    path = PurePosixPath(str(value or "").strip())
    if path.is_absolute() or ".." in path.parts:
        return ""
    parts = list(path.parts)
    if parts[:1] == ["backend"]:
        parts = parts[1:]
    if parts[:1] == ["evidence"]:
        parts = parts[1:]
    return PurePosixPath(*parts).as_posix() if parts else ""


def _load_artifact_payload(
    row: Mapping[str, Any],
    *,
    baseline_path: str | Path,
) -> Mapping[str, Any]:
    raw_path = str(row.get("artifact_path") or "").strip()
    if not raw_path:
        return {}
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        return {}

    evidence_root = Path(baseline_path).resolve().parent
    artifact_path = (evidence_root / Path(*relative.parts)).resolve()
    try:
        artifact_path.relative_to(evidence_root)
    except ValueError:
        return {}
    if not artifact_path.is_file():
        return {}
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _requires_external_archive(
    row: Mapping[str, Any],
    *,
    baseline_path: str | Path,
) -> bool:
    ready = (
        str(row.get("pre_submit_state") or "").strip() == "ready_to_submit"
        and str(row.get("final_status") or "").strip() == "dry_run_passed"
    )
    if not ready:
        return False

    review_id, report_name, _ = _retention_descriptor(row.get("artifact_path"))
    if review_id and report_name:
        return True
    run_id = str(row.get("run_id") or "").strip()
    if _INTERACTIVE_RUN_ID.fullmatch(run_id) or _READY_RUN_ID.fullmatch(run_id):
        return True

    artifact = _load_artifact_payload(row, baseline_path=baseline_path)
    return artifact.get("interactive_handoff") is True


def _load_source_rows(path: Path) -> list[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _safe_archive_names(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for raw_name in archive.namelist():
        path = PurePosixPath(raw_name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe_archive_path")
        if not raw_name.endswith("/"):
            names.append(path.as_posix())
    return names


def _source_values(source: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(source.get("artifact_id") or "").strip(),
        str(source.get("artifact_digest") or "").strip().lower(),
        str(source.get("retained_record_count") or "").strip(),
    )


def _source_archive_path(
    evidence_root: Path,
    review_id: str,
    source: Mapping[str, Any],
) -> Path:
    artifact_id, artifact_digest, _ = _source_values(source)
    return (
        evidence_root
        / ARCHIVE_ROOT_NAME
        / review_id
        / f"artifact-{artifact_id}-{artifact_digest}.zip"
    )


def verify_phase_a_external_archive(
    row: Mapping[str, Any],
    *,
    baseline_path: str | Path,
) -> Dict[str, Any]:
    """Verify durable retention for externally retained Lever Phase A candidates.

    Historical noninteractive records continue to use the verifier-qualified evidence
    contract that existed when they were retained. New interactive-handoff and ordinary
    ready-retention candidates fail closed unless the canonical source manifest and
    durable GitHub artifact zip agree with the retained report.

    One workflow run may retain multiple independently archived candidates. In that
    case, the row is bound to the single source receipt whose archive exists inside the
    row's review-ID directory. Missing or ambiguous bindings fail closed.
    """

    required = _requires_external_archive(row, baseline_path=baseline_path)
    result: Dict[str, Any] = {
        "required": required,
        "verified": not required,
        "archive_path": "",
        "errors": [],
    }
    if not required:
        return result

    baseline = Path(baseline_path).resolve()
    evidence_root = baseline.parent
    run_id = _actions_run_id(row.get("source_reference"))
    review_id, report_name, manifest_name = _retention_descriptor(
        row.get("artifact_path")
    )
    report_digest = str(row.get("artifact_sha256") or "").strip().lower()
    if not run_id:
        result["errors"].append("invalid_actions_source_reference")
    if not review_id or not report_name or not manifest_name:
        result["errors"].append("invalid_external_artifact_path")
    if not _HEX64.fullmatch(report_digest):
        result["errors"].append("invalid_report_digest")
    if result["errors"]:
        return result

    source_rows = [
        source
        for source in _load_source_rows(evidence_root / SOURCE_MANIFEST_NAME)
        if str(source.get("workflow_run_id") or "").strip() == run_id
    ]
    if not source_rows:
        result["errors"].append("missing_or_duplicate_source_manifest_row")
        return result

    archive_path: Path | None = None
    if len(source_rows) == 1:
        source = source_rows[0]
    else:
        matches: list[tuple[Dict[str, str], Path]] = []
        for candidate in source_rows:
            artifact_id, artifact_digest, retained_count = _source_values(candidate)
            if (
                not _DIGITS.fullmatch(artifact_id)
                or not _HEX64.fullmatch(artifact_digest)
                or retained_count != "1"
            ):
                continue
            candidate_path = _source_archive_path(
                evidence_root,
                review_id,
                candidate,
            )
            if candidate_path.is_file():
                matches.append((candidate, candidate_path))
        if len(matches) != 1:
            result["errors"].append("missing_or_duplicate_source_manifest_row")
            return result
        source, archive_path = matches[0]

    artifact_id, artifact_digest, retained_count = _source_values(source)
    if not _DIGITS.fullmatch(artifact_id):
        result["errors"].append("invalid_source_artifact_id")
    if not _HEX64.fullmatch(artifact_digest):
        result["errors"].append("invalid_source_artifact_digest")
    if retained_count != "1":
        result["errors"].append("invalid_source_retained_record_count")
    if result["errors"]:
        return result

    if archive_path is None:
        archive_path = _source_archive_path(evidence_root, review_id, source)
    result["archive_path"] = archive_path.relative_to(evidence_root).as_posix()
    if not archive_path.is_file():
        result["errors"].append("durable_external_archive_missing")
        return result

    archive_bytes = archive_path.read_bytes()
    if _sha256(archive_bytes) != artifact_digest:
        result["errors"].append("durable_external_archive_digest_mismatch")
        return result

    artifact_path = str(row.get("artifact_path") or "").strip()
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = _safe_archive_names(archive)
            report_names = [name for name in names if name.endswith(artifact_path)]
            manifest_names = [name for name in names if name.endswith(manifest_name)]
            if len(report_names) != 1 or len(manifest_names) != 1:
                result["errors"].append("durable_external_archive_members_invalid")
                return result
            retained_report = archive.read(report_names[0])
            manifest = json.loads(archive.read(manifest_names[0]).decode("utf-8"))
    except (ValueError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        result["errors"].append("durable_external_archive_invalid")
        return result

    retained_report_digest = _sha256(retained_report)
    manifest_report = dict(manifest.get("report") or {})
    if retained_report_digest != report_digest:
        result["errors"].append("durable_report_digest_mismatch")
    if (
        manifest.get("repository") != REPOSITORY
        or str(manifest.get("workflow_run_id") or "") != run_id
        or manifest.get("retained_record_count") != 1
        or manifest_report.get("review_id") != review_id
        or _normalized_manifest_report_path(manifest_report.get("path"))
        != artifact_path
        or manifest_report.get("sha256") != report_digest
    ):
        result["errors"].append("durable_retention_manifest_mismatch")

    result["verified"] = not result["errors"]
    return result


__all__ = [
    "ARCHIVE_ROOT_NAME",
    "INTERACTIVE_RETENTION_MANIFEST_NAME",
    "READY_RETENTION_MANIFEST_NAME",
    "RETENTION_MANIFEST_NAME",
    "SOURCE_MANIFEST_NAME",
    "verify_phase_a_external_archive",
]
