"""Verification for the final Lever Phase A evidence replacements."""

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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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
    _require(value["schema_version"] == "1.0", "unexpected_schema_version")
    _require(
        value["reason"] == "stronger_serialized_control_evidence",
        "unexpected_supersession_reason",
    )
    _require(
        value["safety"]
        == {
            "final_submit_clicked": False,
            "historical_archives_preserved": True,
            "quota_credit_counted_once": True,
            "replacement_count": 8,
            "addition_count": 2,
        },
        "unexpected_safety_contract",
    )

    current_runs = {str(record.get("run_id") or "") for record in records}
    current_sources = {_source_key(source) for source in sources}
    replacements = list(value.get("replacements") or [])
    additions = list(value.get("additions") or [])
    _require(
        {item["review_id"] for item in replacements} == EXPECTED_REPLACEMENTS,
        "unexpected_replacement_review_ids",
    )
    _require(
        {item["review_id"] for item in additions} == EXPECTED_ADDITIONS,
        "unexpected_addition_review_ids",
    )
    _require(
        len(replacements) == len(EXPECTED_REPLACEMENTS),
        "unexpected_replacement_count",
    )
    _require(len(additions) == len(EXPECTED_ADDITIONS), "unexpected_addition_count")

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
        _require(_identity(old_row) == target, "superseded_target_mismatch")
        _require(_identity(new_row) == target, "superseding_target_mismatch")
        _require(old_row["run_id"] not in current_runs, "superseded_run_still_current")
        _require(new_row["run_id"] in current_runs, "superseding_run_missing")
        _require(_source_key(old_source) not in current_sources, "superseded_source_still_current")
        _require(_source_key(new_source) in current_sources, "superseding_source_missing")
        _require(new_row["pre_submit_state"] == "ready_to_submit", "superseding_state_not_ready")
        _require(new_row["final_status"] == "dry_run_passed", "superseding_status_not_dry_run")

        archive_path = _safe_historical_archive(
            evidence_root,
            item["superseded"]["archive_path"],
        )
        _require(archive_path.is_file(), "historical_archive_missing")
        _require(
            hashlib.sha256(archive_path.read_bytes()).hexdigest()
            == old_source["artifact_digest"],
            "historical_archive_digest_mismatch",
        )
        replacement_summaries.append({
            "review_id": item["review_id"],
            "superseded_run_id": old_row["run_id"],
            "superseding_run_id": new_row["run_id"],
            "historical_archive": archive_path.relative_to(
                evidence_root.resolve()
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
        _require(_identity(row) == target, "addition_target_mismatch")
        _require(row["run_id"] in current_runs, "addition_run_missing")
        _require(_source_key(source) in current_sources, "addition_source_missing")
        _require(row["pre_submit_state"] == "ready_to_submit", "addition_state_not_ready")
        _require(row["final_status"] == "dry_run_passed", "addition_status_not_dry_run")
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
