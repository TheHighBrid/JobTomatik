import json
from pathlib import Path

import pytest

from app.services.greenhouse_pilot import (
    PilotEvidenceError,
    build_readiness_summary,
    load_ledger,
    merge_records,
    normalize_dry_run_report,
    render_readiness_markdown,
    write_ledger,
)


def _summary(*, submit_clicked=False, employer="Example Inc", outcome="ready_to_submit"):
    return {
        "certification": "greenhouse_supervised_live_dry_run",
        "framework_version": "1.5.0",
        "final_submit_clicked": submit_clicked,
        "reports": [
            {
                "url": "https://boards.greenhouse.io/example/jobs/123",
                "mode": "inspect",
                "passed": True,
                "final_submit_clicked": False,
            },
            {
                "url": "https://boards.greenhouse.io/example/jobs/123",
                "mode": "exercise",
                "passed": True,
                "certification_outcome": outcome,
                "adapter": "greenhouse",
                "adapter_version": "1.1.0",
                "fields_filled": 8,
                "control_evidence_count": 9,
                "review_items": [],
                "validation_errors": [],
                "upload_evidence": [{"verification": "passed"}],
                "final_submit_clicked": submit_clicked,
                "certification_metadata": {
                    "company_name": employer,
                    "job_title": "Fraud Analyst",
                    "board_token": "example",
                    "job_id": "123",
                    "policy_count": 3,
                    "synthetic_profile": True,
                },
            },
        ],
    }


def test_normalizes_only_exercise_records_and_never_counts_inspection():
    records = normalize_dry_run_report(
        _summary(),
        operator="github-actions",
        source_reference="github:123:1",
        completed_at="2026-07-16T20:00:00Z",
    )

    assert len(records) == 1
    record = records[0]
    assert record["mode"] == "dry_run"
    assert record["employer"] == "Example Inc"
    assert record["controls_filled"] == 8
    assert record["uploads_verified"] == 1
    assert record["qualifies_for_dry_run_matrix"] is True
    assert record["final_submit_clicked"] is False


def test_rejects_any_final_submit_activity():
    with pytest.raises(PilotEvidenceError, match="final_submit_clicked=false"):
        normalize_dry_run_report(
            _summary(submit_clicked=True),
            operator="github-actions",
            source_reference="github:123:1",
        )


def test_manual_challenge_is_a_qualifying_safe_dry_run():
    summary = _summary(outcome="manual_challenge_handoff")
    summary["reports"][1]["review_items"] = [
        {
            "reason_code": "captcha_detected",
            "details": {"handoff_stage": "post_fill_pre_action"},
        }
    ]
    records = normalize_dry_run_report(
        summary,
        operator="github-actions",
        source_reference="github:124:1",
    )

    assert records[0]["qualifies_for_dry_run_matrix"] is True
    assert records[0]["final_status"] == "needs_review"
    assert records[0]["handoff_reason"] == "captcha_detected"
    assert records[0]["handoff_boundary"] == "post_fill_pre_action"


def test_ledger_round_trip_and_exact_duplicate_deduplication(tmp_path: Path):
    records = normalize_dry_run_report(
        _summary(),
        operator="github-actions",
        source_reference="github:125:1",
    )
    merged = merge_records(records, records)
    assert len(merged) == 1

    ledger = tmp_path / "pilot.jsonl"
    write_ledger(ledger, merged)
    loaded = load_ledger(ledger)
    assert loaded == merged
    assert json.loads(ledger.read_text().splitlines()[0])["run_id"] == merged[0]["run_id"]


def test_readiness_requires_30_distinct_employers_and_supervised_evidence():
    records = []
    for index in range(30):
        records.extend(
            normalize_dry_run_report(
                _summary(employer=f"Employer {index}"),
                operator="github-actions",
                source_reference=f"github:{index}:1",
            )
        )

    dry_only = build_readiness_summary(records)
    assert dry_only["qualifying_dry_run_count"] == 30
    assert dry_only["distinct_dry_run_employer_count"] == 30
    assert dry_only["gates"]["thirty_qualifying_dry_runs"] is True
    assert dry_only["gates"]["ten_supervised_confirmed_submissions"] is False
    assert dry_only["human_reviewed_submit_ready"] is False

    supervised = []
    for index in range(10):
        supervised.append(
            {
                "run_id": f"supervised-{index}",
                "mode": "supervised_real_submission",
                "final_submit_clicked": True,
                "approval_reference": f"approval-{index}",
                "confirmation_evidence_reference": f"evidence-{index}",
                "confirmation_evidence_type": "confirmation_page",
                "final_status": "confirmed",
                "duplicate_submission_detected": False,
                "reviewed_by": "independent-reviewer",
                "review_reference": f"review-{index}",
                "pre_submit_state": "ready_to_submit",
            }
        )

    ready = build_readiness_summary(
        records + supervised,
        release_approval_reference="release-approval-1",
    )
    assert ready["supervised_confirmed_count"] == 10
    assert ready["human_reviewed_submit_ready"] is True
    markdown = render_readiness_markdown(ready)
    assert "promotion is **READY**" in markdown
    assert "certified_autonomous" in markdown


def test_successful_supervised_record_without_confirmation_is_rejected():
    record = {
        "run_id": "unsafe-supervised",
        "mode": "supervised_real_submission",
        "final_submit_clicked": True,
        "approval_reference": "approval-1",
        "confirmation_evidence_reference": None,
        "final_status": "submitted",
    }
    with pytest.raises(PilotEvidenceError, match="confirmation evidence"):
        build_readiness_summary([record])
