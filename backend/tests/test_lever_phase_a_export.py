import csv
import json

import pytest

from app.services.ats_lever import LEVER_ADAPTER_VERSION
from app.services.lever_pilot_ingestion import load_phase_a_baseline
from scripts.export_lever_phase_a_record import (
    LeverPhaseAExportError,
    build_phase_a_candidate,
    export_phase_a_candidate,
)


POSTING_ID = "12345678-1234-1234-1234-123456789abc"
LEVER_URL = f"https://jobs.eu.lever.co/exportco/{POSTING_ID}/apply"


def _report(*, clicked=False, outcome="ready_to_submit"):
    return {
        "certification": "lever_supervised_live_dry_run",
        "final_submit_clicked": clicked,
        "passed": not clicked,
        "reports": [
            {
                "url": LEVER_URL,
                "mode": "inspect",
                "passed": True,
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "final_submit_clicked": False,
                "dom": {"visible_control_count": 12},
            },
            {
                "url": LEVER_URL,
                "mode": "exercise",
                "passed": not clicked,
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "certification_outcome": outcome,
                "fields_filled": 8,
                "control_evidence_count": 8,
                "validation_errors": [],
                "review_items": [],
                "upload_evidence": [{"verification": "passed"}],
                "final_submit_clicked": clicked,
                "error": None,
            },
        ],
    }


def test_exported_phase_a_candidate_is_canonical_and_never_mutates_baseline(tmp_path):
    report_path = tmp_path / "lever-report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    candidate_path = tmp_path / "lever-phase-a-candidate.csv"

    record = build_phase_a_candidate(
        _report(),
        report_path=report_path,
        run_id="gha-123",
        operator="github-actions",
        source_reference="https://github.com/example/actions/runs/123",
        employer="Export Co",
        role="Risk Analyst",
        completed_at="2026-07-27T20:00:00+00:00",
    )
    export_phase_a_candidate(candidate_path, record)

    loaded = load_phase_a_baseline(candidate_path)
    assert len(loaded) == 1
    assert loaded[0]["qualifies_for_dry_run_matrix"] is True
    assert loaded[0]["final_submit_clicked"] is False
    assert loaded[0]["region"] == "eu"
    assert loaded[0]["site"] == "exportco"
    assert loaded[0]["posting_id"] == POSTING_ID
    assert loaded[0]["source_reference"].endswith("/123")
    assert not (tmp_path / "lever-phase-a-baseline.csv").exists()

    with candidate_path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["pre_submit_state"] == "ready_to_submit"
    assert row["final_status"] == "dry_run_passed"
    assert len(row["artifact_sha256"]) == 64


def test_export_fails_closed_when_any_final_submit_click_is_observed(tmp_path):
    report = _report(clicked=True)
    report_path = tmp_path / "unsafe-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(LeverPhaseAExportError, match="final_submit_clicked=false"):
        build_phase_a_candidate(
            report,
            report_path=report_path,
            run_id="gha-unsafe",
            operator="github-actions",
            source_reference="https://github.com/example/actions/runs/unsafe",
            employer="Export Co",
            role="Risk Analyst",
        )


def test_manual_challenge_candidate_uses_needs_review_outcome(tmp_path):
    report = _report(outcome="manual_challenge_handoff")
    exercise = report["reports"][1]
    exercise["review_items"] = [
        {
            "reason_code": "captcha_detected",
            "details": {"handoff_stage": "post_fill_pre_action"},
        }
    ]
    report_path = tmp_path / "handoff-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    record = build_phase_a_candidate(
        report,
        report_path=report_path,
        run_id="gha-handoff",
        operator="github-actions",
        source_reference="https://github.com/example/actions/runs/handoff",
        employer="Export Co",
        role="Risk Analyst",
    )

    assert record["pre_submit_state"] == "manual_challenge_handoff"
    assert record["final_status"] == "needs_review"
    assert record["handoff_reason"] == "captcha_detected"
    assert record["handoff_boundary"] == "post_fill_pre_action"
