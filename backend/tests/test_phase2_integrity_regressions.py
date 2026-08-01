from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from app.services.ats_lever import LEVER_ADAPTER_VERSION
from app.services.lever_pilot_ingestion import load_phase_a_baseline
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness
from app.services.lever_readiness_hardening import harden_lever_readiness
from app.services.operational_safety import _posting_identity


FIELDS = [
    "run_id",
    "completed_at",
    "employer",
    "role",
    "site",
    "posting_id",
    "region",
    "application_url",
    "adapter_version",
    "operator",
    "source_reference",
    "artifact_sha256",
    "artifact_path",
    "official_posting_inspection_passed",
    "pre_submit_state",
    "final_status",
]
SOURCE_FIELDS = [
    "workflow_run_id",
    "artifact_id",
    "artifact_digest",
    "retained_record_count",
]


def _report(url: str, *, include_inspection: bool = True) -> dict:
    reports = []
    if include_inspection:
        reports.append(
            {
                "url": url,
                "mode": "inspect",
                "passed": True,
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "final_submit_clicked": False,
            }
        )
    reports.append(
        {
            "url": url,
            "mode": "exercise",
            "passed": True,
            "adapter": "lever",
            "adapter_version": LEVER_ADAPTER_VERSION,
            "certification_outcome": "ready_to_submit",
            "final_submit_clicked": False,
        }
    )
    return {"final_submit_clicked": False, "reports": reports}


def _append_source(root: Path, row: dict[str, str]) -> None:
    source_path = root / "lever-phase-a-sources.csv"
    exists = source_path.exists()
    with source_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def _row(root: Path, index: int, *, include_inspection: bool = True) -> dict:
    region = "eu" if index % 2 == 0 else "global"
    host = "jobs.eu.lever.co" if region == "eu" else "jobs.lever.co"
    site = f"site-{index}"
    posting = f"00000000-0000-0000-0000-{index:012d}"
    url = f"https://{host}/{site}/{posting}/apply"
    review_id = f"D8-{index:03d}"
    artifact_path = (
        Path("lever-phase-a-artifacts")
        / review_id
        / "lever-phase-a-interactive-report.json"
    )
    artifact = root / artifact_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    report_bytes = json.dumps(
        _report(url, include_inspection=include_inspection),
        sort_keys=True,
    ).encode("utf-8")
    artifact.write_bytes(report_bytes)
    report_digest = hashlib.sha256(report_bytes).hexdigest()

    workflow_run_id = str(800000000 + index)
    artifact_id = str(900000000 + index)
    manifest = {
        "repository": "TheHighBrid/JobTomatik",
        "workflow_run_id": workflow_run_id,
        "retained_record_count": 1,
        "report": {
            "review_id": review_id,
            "path": artifact_path.as_posix(),
            "sha256": report_digest,
        },
    }
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(artifact_path.as_posix(), report_bytes)
        archive.writestr(
            "lever-phase-a-interactive-retention-manifest.json",
            json.dumps(manifest, sort_keys=True).encode("utf-8"),
        )
    archive_bytes = archive_buffer.getvalue()
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    archive_path = (
        root
        / "lever-phase-a-external-archives"
        / review_id
        / f"artifact-{artifact_id}-{archive_digest}.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive_bytes)
    _append_source(
        root,
        {
            "workflow_run_id": workflow_run_id,
            "artifact_id": artifact_id,
            "artifact_digest": archive_digest,
            "retained_record_count": "1",
        },
    )

    return {
        "run_id": f"run-{index}",
        "completed_at": "2026-07-29T00:00:00+00:00",
        "employer": f"Employer {index}",
        "role": "Engineer",
        "site": site,
        "posting_id": posting,
        "region": region,
        "application_url": url,
        "adapter_version": LEVER_ADAPTER_VERSION,
        "operator": "test",
        "source_reference": (
            "https://github.com/TheHighBrid/JobTomatik/actions/runs/"
            + workflow_run_id
        ),
        "artifact_sha256": report_digest,
        "artifact_path": artifact_path.as_posix(),
        "official_posting_inspection_passed": "true",
        "pre_submit_state": "ready_to_submit",
        "final_status": "dry_run_passed",
    }


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_first_verified_run_advances_count_without_changing_launch_snapshot(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    _write(baseline, [_row(tmp_path, 1)])
    readiness = read_lever_pilot_readiness(
        baseline_path=baseline,
        ledger_path=tmp_path / "missing.jsonl",
    )
    assert readiness["summary"]["qualifying_dry_run_count"] == 1


def test_thirty_verified_runs_pass_despite_historical_captcha_rows(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    boundary = {
        **_row(tmp_path, 99),
        "run_id": "historical-captcha",
        "artifact_path": "",
        "pre_submit_state": "manual_challenge_handoff",
        "final_status": "needs_review",
        "official_posting_inspection_passed": "false",
    }
    rows = [boundary, *[_row(tmp_path, index) for index in range(1, 31)]]
    _write(baseline, rows)
    summary = harden_lever_readiness(
        {"summary": {"platform": "lever", "canonical_maturity": "dry_run", "gates": {}}},
        baseline_path=baseline,
        ledger_path=tmp_path / "missing.jsonl",
    )["summary"]
    assert summary["qualifying_dry_run_count"] == 30
    assert summary["manual_challenge_boundary_count"] == 1
    assert summary["phase_a_inspection_failure_count"] == 0
    assert summary["phase_a_external_archive_failure_count"] == 0
    assert summary["gates"]["thirty_qualifying_dry_runs"] is True
    assert summary["gates"][
        "all_qualifying_phase_a_records_have_durable_external_archives"
    ] is True


def test_csv_flag_and_matching_digest_cannot_forge_inspection(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    _write(baseline, [_row(tmp_path, 1, include_inspection=False)])
    record = load_phase_a_baseline(baseline)[0]
    assert record["phase_a_artifact_verified"] is True
    assert record["official_posting_inspection_passed"] is True
    assert record["official_posting_inspection_verified"] is False
    assert record["qualifies_for_dry_run_matrix"] is False


def test_greenhouse_query_ids_remain_distinct_posting_identities():
    assert _posting_identity("https://boards.greenhouse.io/acme?gh_jid=111") != _posting_identity(
        "https://boards.greenhouse.io/acme?gh_jid=222"
    )
    assert _posting_identity(
        "https://boards.greenhouse.io/embed/job_app?token=alpha"
    ) != _posting_identity(
        "https://boards.greenhouse.io/embed/job_app?token=beta"
    )