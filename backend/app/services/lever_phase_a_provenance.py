"""External provenance contract for interactive Lever Phase A evidence."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, Mapping

from app.services.lever_phase_a_operator import load_locked_target
from app.services.lever_pilot_ingestion import load_phase_a_baseline
from scripts.export_lever_phase_a_record import (
    build_phase_a_candidate,
    export_phase_a_candidate,
)


REPOSITORY = "TheHighBrid/JobTomatik"
ACTIONS_RUN_PREFIX = f"https://github.com/{REPOSITORY}/actions/runs/"
SOURCE_FIELDNAMES = [
    "workflow_run_id",
    "artifact_id",
    "artifact_digest",
    "retained_record_count",
]
_REPORT_NAME = "lever-phase-a-interactive-report.json"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DIGITS = re.compile(r"[1-9][0-9]*")


class LeverPhaseAProvenanceError(ValueError):
    pass


def validate_external_provenance(
    *,
    workflow_run_id: str,
    artifact_id: str,
    artifact_digest: str,
) -> Dict[str, str]:
    run_id = str(workflow_run_id or "").strip()
    retained_artifact_id = str(artifact_id or "").strip()
    digest = str(artifact_digest or "").strip().lower()
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


def write_source_receipt(
    output_path: Path,
    provenance: Mapping[str, str],
) -> None:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "workflow_run_id": provenance["workflow_run_id"],
        "artifact_id": provenance["artifact_id"],
        "artifact_digest": provenance["artifact_digest"],
        "retained_record_count": 1,
    }
    temporary = target.with_name(f".{target.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_FIELDNAMES)
        writer.writeheader()
        writer.writerow(row)
    temporary.replace(target)


def finalize_interactive_candidate(
    report: Mapping[str, Any],
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
    run_id: str | None = None,
) -> Dict[str, Any]:
    target = load_locked_target(review_id, corpus_root)
    provenance = validate_external_provenance(
        workflow_run_id=workflow_run_id,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )
    artifact_path = require_retained_report_path(report_path, evidence_root)
    expected_review_id = str(
        ((report.get("reports") or [{}, {}])[1].get("certification_metadata") or {}).get(
            "review_id"
        )
        or ""
    ).strip()
    if expected_review_id != str(target["review_id"]):
        raise LeverPhaseAProvenanceError(
            "The retained report does not match the requested frozen review ID"
        )
    final_run_id = str(run_id or "").strip() or (
        f"github-actions-{provenance['workflow_run_id']}-interactive-"
        f"{str(target['review_id']).lower()}"
    )
    record = build_phase_a_candidate(
        report,
        report_path=Path(report_path),
        output_path=Path(candidate_path),
        artifact_path=artifact_path,
        run_id=final_run_id,
        operator=operator,
        source_reference=provenance["source_reference"],
        employer=str(target["employer"]),
        role=str(target["role"]),
    )
    export_phase_a_candidate(Path(candidate_path), record)
    loaded = load_phase_a_baseline(Path(candidate_path))
    if len(loaded) != 1 or loaded[0].get("qualifies_for_dry_run_matrix") is not True:
        raise LeverPhaseAProvenanceError(
            "The externally retained interactive candidate did not qualify"
        )
    write_source_receipt(Path(source_receipt_path), provenance)
    return {
        "candidate": record,
        "source_receipt": {
            "workflow_run_id": provenance["workflow_run_id"],
            "artifact_id": provenance["artifact_id"],
            "artifact_digest": provenance["artifact_digest"],
            "retained_record_count": 1,
        },
    }


__all__ = [
    "ACTIONS_RUN_PREFIX",
    "LeverPhaseAProvenanceError",
    "SOURCE_FIELDNAMES",
    "finalize_interactive_candidate",
    "require_retained_report_path",
    "validate_external_provenance",
    "write_source_receipt",
]
