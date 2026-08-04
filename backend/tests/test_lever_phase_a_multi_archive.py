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


def _row(review_id: str, run_id: str) -> dict:
    return {
        "run_id": f"github-actions-{run_id}-ready-{review_id.lower()}",
        "source_reference": (
            f"https://github.com/TheHighBrid/JobTomatik/actions/runs/{run_id}"
        ),
        "artifact_path": (
            f"lever-phase-a-artifacts/{review_id}/lever-phase-a-report.json"
        ),
        "artifact_sha256": "",
        "pre_submit_state": "ready_to_submit",
        "final_status": "dry_run_passed",
    }


def _archive(tmp_path: Path, row: dict, review_id: str, run_id: str, artifact_id: str):
    report = json.dumps({"review_id": review_id, "passed": True}).encode() + b"\n"
    report_digest = _sha256(report)
    row["artifact_sha256"] = report_digest
    manifest = {
        "repository": "TheHighBrid/JobTomatik",
        "workflow_run_id": run_id,
        "retained_record_count": 1,
        "report": {
            "review_id": review_id,
            "path": f'evidence/{row["artifact_path"]}',
            "sha256": report_digest,
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f'evidence/{row["artifact_path"]}', report)
        archive.writestr(
            READY_RETENTION_MANIFEST_NAME,
            json.dumps(manifest, sort_keys=True).encode(),
        )
    archive_bytes = buffer.getvalue()
    archive_digest = _sha256(archive_bytes)
    archive_path = (
        tmp_path
        / ARCHIVE_ROOT_NAME
        / review_id
        / f"artifact-{artifact_id}-{archive_digest}.zip"
    )
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(archive_bytes)
    return archive_digest, archive_path


def test_rows_from_one_workflow_bind_to_their_own_review_archives(tmp_path: Path):
    baseline = tmp_path / "lever-phase-a-baseline.csv"
    baseline.write_text("run_id\n", encoding="utf-8")
    run_id = "30871406281"
    first = _row("D8-005", run_id)
    second = _row("D8-006", run_id)
    first_digest, first_archive = _archive(
        tmp_path, first, "D8-005", run_id, "8878114105"
    )
    second_digest, second_archive = _archive(
        tmp_path, second, "D8-006", run_id, "8878114106"
    )

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
        writer.writerows(
            [
                {
                    "workflow_run_id": run_id,
                    "artifact_id": "8878114105",
                    "artifact_digest": first_digest,
                    "retained_record_count": "1",
                },
                {
                    "workflow_run_id": run_id,
                    "artifact_id": "8878114106",
                    "artifact_digest": second_digest,
                    "retained_record_count": "1",
                },
            ]
        )

    first_result = verify_phase_a_external_archive(first, baseline_path=baseline)
    second_result = verify_phase_a_external_archive(second, baseline_path=baseline)

    assert first_result == {
        "required": True,
        "verified": True,
        "archive_path": first_archive.relative_to(tmp_path).as_posix(),
        "errors": [],
    }
    assert second_result == {
        "required": True,
        "verified": True,
        "archive_path": second_archive.relative_to(tmp_path).as_posix(),
        "errors": [],
    }
