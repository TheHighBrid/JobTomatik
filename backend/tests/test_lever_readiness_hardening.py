from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.services.lever_readiness_hardening import harden_lever_readiness


FIELDNAMES = [
    "run_id",
    "site",
    "posting_id",
    "region",
    "pre_submit_state",
    "final_status",
    "official_posting_inspection_passed",
]


def _write_phase_a(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _write_phase_b(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _base_readiness() -> dict[str, object]:
    return {
        "summary": {
            "platform": "lever",
            "canonical_maturity": "dry_run",
            "gates": {"explicit_separate_promotion_approval": False},
            "promotion_ready": False,
        }
    }


def _phase_b_record(index: int) -> dict[str, object]:
    suffix = f"{index:02d}"
    payload_hash = (f"{index + 1:064x}")[-64:]
    return {
        "mode": "supervised_real_submission",
        "run_id": f"run-{suffix}",
        "approval_reference": f"lvsup-{suffix}",
        "reviewed_by": f"reviewer-{suffix}",
        "review_reference": f"review-{suffix}",
        "confirmation_evidence_reference": f"evidence-{suffix}",
        "final_status": "confirmed",
        "pre_submit_state": "submitted",
        "duplicate_submission_detected": False,
        "site": f"site-{suffix}",
        "posting_id": f"posting-{suffix}",
        "region": "global" if index % 2 == 0 else "eu",
        "evidence_payload_hash": payload_hash,
        "combined_payload_hash": payload_hash,
    }


def test_manual_challenge_is_boundary_coverage_not_qualifying_phase_a(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    _write_phase_a(
        baseline,
        [
            {
                "run_id": "captcha-run",
                "site": "example",
                "posting_id": "posting-1",
                "region": "global",
                "pre_submit_state": "manual_challenge_handoff",
                "final_status": "needs_review",
                "official_posting_inspection_passed": "true",
            }
        ],
    )

    payload = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )
    summary = payload["summary"]

    assert summary["qualifying_dry_run_count"] == 0
    assert summary["manual_challenge_boundary_count"] == 1
    assert summary["nonqualifying_dry_run_count"] == 1
    assert summary["gates"]["thirty_qualifying_dry_runs"] is False


def test_ready_outcome_requires_successful_matching_inspection(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    _write_phase_a(
        baseline,
        [
            {
                "run_id": "missing-inspection",
                "site": "example",
                "posting_id": "posting-1",
                "region": "global",
                "pre_submit_state": "ready_to_submit",
                "final_status": "dry_run_passed",
                "official_posting_inspection_passed": "false",
            }
        ],
    )

    payload = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )
    summary = payload["summary"]

    assert summary["qualifying_dry_run_count"] == 0
    assert summary["phase_a_inspection_failure_count"] == 1
    assert (
        summary["gates"]["all_phase_a_records_have_successful_matching_inspection"]
        is False
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_confirmation",
        "missing_review",
        "payload_hash_mismatch",
        "duplicate_outcome",
        "uncertain_outcome",
    ],
)
def test_phase_b_threshold_uses_only_fully_safe_evidence(tmp_path, mutation):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    records = [_phase_b_record(index) for index in range(10)]

    if mutation == "missing_confirmation":
        records[0]["confirmation_evidence_reference"] = ""
    elif mutation == "missing_review":
        records[0]["reviewed_by"] = ""
    elif mutation == "payload_hash_mismatch":
        records[0]["evidence_payload_hash"] = "f" * 64
    elif mutation == "duplicate_outcome":
        records[1]["approval_reference"] = records[0]["approval_reference"]
    elif mutation == "uncertain_outcome":
        records[0]["pre_submit_state"] = "submission_uncertain"

    _write_phase_b(ledger, records)
    payload = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )
    summary = payload["summary"]

    assert summary["raw_supervised_confirmed_count"] == 10
    assert summary["supervised_confirmed_count"] < 10
    assert summary["gates"]["ten_supervised_confirmed_submissions"] is False
    assert summary["supervised_pilot_evidence_complete"] is False


def test_ten_fully_safe_phase_b_records_satisfy_only_the_phase_b_gate(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    _write_phase_b(ledger, [_phase_b_record(index) for index in range(10)])

    payload = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )
    summary = payload["summary"]

    assert summary["supervised_confirmed_count"] == 10
    assert summary["gates"]["ten_supervised_confirmed_submissions"] is True
    assert summary["gates"]["all_success_evidence_independently_reviewed"] is True
    assert summary["gates"]["all_evidence_hashes_match_consumed_approvals"] is True
    assert summary["supervised_pilot_evidence_complete"] is False
    assert summary["promotion_ready"] is False

def test_candidate_rows_without_retained_artifacts_fail_closed(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    rows = [{
        "run_id": "historical-captcha",
        "site": "historical-site",
        "posting_id": "historical-posting",
        "region": "global",
        "pre_submit_state": "manual_challenge_handoff",
        "final_status": "needs_review",
        "official_posting_inspection_passed": "false",
    }]
    rows.extend({
        "run_id": f"unsupported-{index}",
        "site": f"site-{index}",
        "posting_id": f"posting-{index}",
        "region": "global" if index % 2 else "eu",
        "pre_submit_state": "ready_to_submit",
        "final_status": "dry_run_passed",
        "official_posting_inspection_passed": "true",
    } for index in range(30))
    _write_phase_a(baseline, rows)
    summary = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )["summary"]
    assert summary["qualifying_dry_run_count"] == 0
    assert summary["manual_challenge_boundary_count"] == 1
    assert summary["phase_a_inspection_failure_count"] == 30
    assert summary["gates"]["thirty_qualifying_dry_runs"] is False


def test_duplicate_indicator_on_blocked_phase_b_record_fails_duplicate_gate(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    records = [_phase_b_record(index) for index in range(10)]
    blocked = _phase_b_record(99)
    blocked.update({
        "final_status": "blocked",
        "pre_submit_state": "blocked",
        "duplicate_submission_detected": True,
    })
    records.append(blocked)
    _write_phase_b(ledger, records)
    summary = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )["summary"]
    assert summary["raw_supervised_confirmed_count"] == 10
    assert summary["supervised_confirmed_count"] == 10
    assert summary["duplicate_submission_count"] == 1
    assert summary["gates"]["zero_duplicate_submissions"] is False
    assert summary["supervised_pilot_evidence_complete"] is False
