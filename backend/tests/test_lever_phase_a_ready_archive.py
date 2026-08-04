import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from app.services.lever_phase_a_archive import (
    ARCHIVE_ROOT_NAME,
    READY_RETENTION_MANIFEST_NAME,
    SOURCE_MANIFEST_NAME,
    verify_phase_a_external_archive,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ready_row() -> dict:
    return {
        "run_id": "github-actions-30862050704-ready-d8-003",
        "source_reference": (
            "https://github.com/TheHighBrid/JobTomatik/actions/runs/30862050704"
        ),
        "artifact_path": "lever-phase-a-artifacts/D8-003/lever-phase-a-report.json",
        "artifact_sha256": "a" * 64,
        "pre_submit_state": "ready_to_submit",
        "final_status": "dry_run_passed",
    }


def _retain_ready_archive(tmp_path: Path, row: dict) -> Path:
    report = b'{"passed": true}\n'
    report_digest = _sha256(report)
    row["artifact_sha256"] = report_digest
    manifest = {
        "repository": "TheHighBrid/JobTomatik",
        "workflow_run_id": "30862050704",
        "retained_record_count": 1,
        "report": {
            "review_id": "D8-003",
            "path": f'evidence/{row["artifact_path"]}',
            "sha256": report_digest,
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f'evidence/{row["artifact_path"]}', report)
        archive.writestr(
            READY_RETENTION_MANIFEST_NAME,
            json.dumps(manifest, sort_keys=True).encode("utf-8"),
        )
    archive_bytes = buffer.getvalue()
    archive_digest = _sha256(archive_bytes)
    artifact_id = "123456789"
    archive_path = (
        tmp_path
        / ARCHIVE_ROOT_NAME
        / "D8-003"
        / f"artifact-{artifact_id}-{archive_digest}.zip"
    )
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(archive_bytes)

    with (tmp_path / SOURCE_MANIFEST_NAME).open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "workflow_run_id",
                "artifact_id",
                "artifact_digest",
                "retained_record_count",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "workflow_run_id": "30862050704",
                "artifact_id": artifact_id,
                "artifact_digest": archive_digest,
                "retained_record_count": "1",
            }
        )
    return archive_path


def test_ready_retention_row_requires_durable_external_archive(tmp_path: Path):
    baseline = tmp_path / "lever-phase-a-baseline.csv"
    baseline.write_text("run_id\n", encoding="utf-8")

    result = verify_phase_a_external_archive(
        _ready_row(),
        baseline_path=baseline,
    )

    assert result["required"] is True
    assert result["verified"] is False
    assert result["errors"] == ["missing_or_duplicate_source_manifest_row"]


def test_ready_retention_manifest_accepts_evidence_prefix(tmp_path: Path):
    baseline = tmp_path / "lever-phase-a-baseline.csv"
    baseline.write_text("run_id\n", encoding="utf-8")
    row = _ready_row()
    archive_path = _retain_ready_archive(tmp_path, row)

    result = verify_phase_a_external_archive(row, baseline_path=baseline)

    assert result == {
        "required": True,
        "verified": True,
        "archive_path": archive_path.relative_to(tmp_path).as_posix(),
        "errors": [],
    }


def test_nonqualifying_ready_path_does_not_create_archive_requirement(tmp_path: Path):
    baseline = tmp_path / "lever-phase-a-baseline.csv"
    baseline.write_text("run_id\n", encoding="utf-8")
    row = _ready_row()
    row["pre_submit_state"] = "manual_challenge_handoff"
    row["final_status"] = "needs_review"

    result = verify_phase_a_external_archive(row, baseline_path=baseline)

    assert result == {
        "required": False,
        "verified": True,
        "archive_path": "",
        "errors": [],
    }
