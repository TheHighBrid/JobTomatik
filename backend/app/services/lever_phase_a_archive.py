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
RETENTION_MANIFEST_NAME = "lever-phase-a-interactive-retention-manifest.json"
ARCHIVE_ROOT_NAME = "lever-phase-a-external-archives"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DIGITS = re.compile(r"[1-9][0-9]*")
_INTERACTIVE_RUN_ID = re.compile(
    r"github-actions-[1-9][0-9]*-interactive-d8-[0-9]{3}",
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


def _review_id_from_artifact_path(artifact_path: Any) -> str:
    path = PurePosixPath(str(artifact_path or "").strip())
    if (
        len(path.parts) == 3
        and path.parts[0] == "lever-phase-a-artifacts"
        and path.parts[2] == "lever-phase-a-interactive-report.json"
        and re.fullmatch(r"D8-[0-9]{3}", path.parts[1])
    ):
        return path.parts[1]
    return ""


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

    if _review_id_from_artifact_path(row.get("artifact_path")):
        return True
    if _INTERACTIVE_RUN_ID.fullmatch(str(row.get("run_id") or "").strip()):
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


def verify_phase_a_external_archive(
    row: Mapping[str, Any],
    *,
    baseline_path: str | Path,
) -> Dict[str, Any]:
    """Verify durable retention for interactive Lever Phase A candidates.

    Historical noninteractive records continue to use the verifier-qualified evidence
    contract that existed when they were retained. New interactive-handoff candidates
    fail closed unless the canonical source manifest and durable GitHub artifact zip
    agree with the retained report.
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
    review_id = _review_id_from_artifact_path(row.get("artifact_path"))
    report_digest = str(row.get("artifact_sha256") or "").strip().lower()
    if not run_id:
        result["errors"].append("invalid_actions_source_reference")
    if not review_id:
        result["errors"].append("invalid_interactive_artifact_path")
    if not _HEX64.fullmatch(report_digest):
        result["errors"].append("invalid_report_digest")

    source_rows = [
        source
        for source in _load_source_rows(evidence_root / SOURCE_MANIFEST_NAME)
        if str(source.get("workflow_run_id") or "").strip() == run_id
    ]
    if len(source_rows) != 1:
        result["errors"].append("missing_or_duplicate_source_manifest_row")
        return result

    source = source_rows[0]
    artifact_id = str(source.get("artifact_id") or "").strip()
    artifact_digest = str(source.get("artifact_digest") or "").strip().lower()
    retained_count = str(source.get("retained_record_count") or "").strip()
    if not _DIGITS.fullmatch(artifact_id):
        result["errors"].append("invalid_source_artifact_id")
    if not _HEX64.fullmatch(artifact_digest):
        result["errors"].append("invalid_source_artifact_digest")
    if retained_count != "1":
        result["errors"].append("invalid_source_retained_record_count")
    if result["errors"]:
        return result

    archive_path = (
        evidence_root
        / ARCHIVE_ROOT_NAME
        / review_id
        / f"artifact-{artifact_id}-{artifact_digest}.zip"
    )
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
            manifest_names = [
                name for name in names if name.endswith(RETENTION_MANIFEST_NAME)
            ]
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
        or manifest_report.get("path") != artifact_path
        or manifest_report.get("sha256") != report_digest
    ):
        result["errors"].append("durable_retention_manifest_mismatch")

    result["verified"] = not result["errors"]
    return result


__all__ = [
    "ARCHIVE_ROOT_NAME",
    "RETENTION_MANIFEST_NAME",
    "SOURCE_MANIFEST_NAME",
    "verify_phase_a_external_archive",
]
