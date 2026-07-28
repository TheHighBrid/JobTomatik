import csv
from datetime import datetime

import pytest

from app.services.lever_pilot_ingestion import (
    LeverPilotIngestionError,
    build_readiness_summary,
    load_phase_a_baseline,
)


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
    "official_posting_inspection_passed",
    "pre_submit_state",
    "final_status",
]


def _row(**overrides):
    site = "phase-a-site"
    posting_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    row = {
        "run_id": "lv-phase-a-1",
        "completed_at": datetime.utcnow().isoformat(),
        "employer": "Phase A Employer",
        "role": "Analyst",
        "site": site,
        "posting_id": posting_id,
        "region": "global",
        "application_url": f"https://jobs.lever.co/{site}/{posting_id}/apply",
        "adapter_version": "1.1.0",
        "operator": "github-actions:TheHighBrid",
        "source_reference": "actions-run:123:artifact:lever-phase-a-1",
        "artifact_sha256": "a" * 64,
        "official_posting_inspection_passed": "true",
        "pre_submit_state": "ready_to_submit",
        "final_status": "dry_run_passed",
    }
    row.update(overrides)
    return row


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_failed_phase_a_row_remains_visible_but_never_counts_for_readiness(tmp_path):
    path = tmp_path / "phase-a.csv"
    _write(
        path,
        [_row(pre_submit_state="failed", final_status="failed")],
    )

    records = load_phase_a_baseline(path)
    summary = build_readiness_summary(records)

    assert len(records) == 1
    assert records[0]["qualifies_for_dry_run_matrix"] is False
    assert summary["record_count"] == 1
    assert summary["qualifying_dry_run_count"] == 0
    assert summary["nonqualifying_dry_run_count"] == 1
    assert summary["distinct_site_count"] == 0
    assert summary["gates"]["thirty_qualifying_dry_runs"] is False
    assert summary["gates"]["thirty_distinct_lever_sites"] is False


def test_invalid_non_hex_artifact_digest_is_rejected(tmp_path):
    path = tmp_path / "phase-a.csv"
    _write(path, [_row(artifact_sha256="z" * 64)])

    with pytest.raises(LeverPilotIngestionError, match="hexadecimal SHA-256"):
        load_phase_a_baseline(path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"application_url": "https://jobs.lever.co/other-site/bbbbbbbb-cccc-dddd-eeee-ffffffffffff/apply"},
        {"application_url": "https://jobs.lever.co/phase-a-site/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/apply"},
        {"region": "eu"},
    ],
)
def test_phase_a_canonical_url_must_match_claimed_target(tmp_path, overrides):
    path = tmp_path / "phase-a.csv"
    _write(path, [_row(**overrides)])

    with pytest.raises(LeverPilotIngestionError, match="canonical_application_url"):
        load_phase_a_baseline(path)


def test_missing_adapter_version_is_rejected_instead_of_defaulted(tmp_path):
    path = tmp_path / "phase-a.csv"
    _write(path, [_row(adapter_version="")])

    with pytest.raises(LeverPilotIngestionError, match="adapter_version.*explicitly recorded"):
        load_phase_a_baseline(path)


def test_historical_adapter_version_is_not_credited_to_current_pilot(tmp_path):
    path = tmp_path / "phase-a.csv"
    _write(path, [_row(adapter_version="1.0.0")])

    with pytest.raises(LeverPilotIngestionError, match="adapter_version.*1.1.0"):
        load_phase_a_baseline(path)


def test_explicit_success_with_exact_identity_counts(tmp_path):
    path = tmp_path / "phase-a.csv"
    _write(path, [_row()])

    records = load_phase_a_baseline(path)
    summary = build_readiness_summary(records)

    assert records[0]["qualifies_for_dry_run_matrix"] is True
    assert summary["qualifying_dry_run_count"] == 1
    assert summary["distinct_site_count"] == 1
    assert summary["regions_covered"] == ["global"]


def test_ready_pair_without_successful_inspection_does_not_qualify(tmp_path):
    path = tmp_path / "phase-a.csv"
    _write(path, [_row(official_posting_inspection_passed="false")])

    records = load_phase_a_baseline(path)
    summary = build_readiness_summary(records)

    assert records[0]["official_posting_inspection_passed"] is False
    assert records[0]["qualifies_for_dry_run_matrix"] is False
    assert summary["qualifying_dry_run_count"] == 0
