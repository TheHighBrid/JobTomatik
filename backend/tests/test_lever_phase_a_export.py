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


def _report(*, clicked=False, outcome="ready_to_submit", inspection_passed=True):
    exercise = {
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
    }
    if outcome == "manual_challenge_handoff":
        exercise.update(
            {
                "manual_challenge_ready": True,
                "ready_to_submit": False,
                "requires_manual_review": True,
            }
        )
    return {
        "certification": "lever_supervised_live_dry_run",
        "final_submit_clicked": clicked,
        "passed": not clicked and inspection_passed,
        "reports": [
            {
                "url": LEVER_URL,
                "mode": "inspect",
                "passed": inspection_passed,
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "final_submit_clicked": False,
                "dom": {"visible_control_count": 12},
            },
            exercise,
        ],
    }


def _build(tmp_path, report):
    report_path = tmp_path / "lever-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return build_phase_a_candidate(
        report,
        report_path=report_path,
        run_id="gha-123",
        operator="github-actions",
        source_reference="https://github.com/example/actions/runs/123",
        employer="Export Co",
        role="Risk Analyst",
        completed_at="2026-07-27T20:00:00+00:00",
    )


def test_exported_phase_a_candidate_is_canonical_and_never_mutates_baseline(tmp_path):
    record = _build(tmp_path, _report())
    candidate_path = tmp_path / "lever-phase-a-candidate.csv"
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
    assert row["official_posting_inspection_passed"] == "True"
    assert row["controls_skipped"] == "4"
    assert len(row["artifact_sha256"]) == 64


def test_export_fails_closed_when_any_final_submit_click_is_observed(tmp_path):
    report = _report(clicked=True)

    with pytest.raises(LeverPhaseAExportError, match="final_submit_clicked=false"):
        _build(tmp_path, report)


@pytest.mark.parametrize("inspection_mode", ["missing", "failed"])
def test_export_requires_one_successful_matching_official_inspection(tmp_path, inspection_mode):
    report = _report(inspection_passed=inspection_mode != "failed")
    if inspection_mode == "missing":
        report["reports"] = [item for item in report["reports"] if item["mode"] != "inspect"]

    with pytest.raises(LeverPhaseAExportError, match="inspection"):
        _build(tmp_path, report)


def test_manual_challenge_candidate_is_verified_boundary_only_evidence(tmp_path):
    report = _report(outcome="manual_challenge_handoff")
    exercise = report["reports"][1]
    exercise["review_items"] = [
        {
            "reason_code": "captcha_detected",
            "details": {"handoff_stage": "post_fill_pre_action"},
        }
    ]

    record = _build(tmp_path, report)
    candidate_path = tmp_path / "lever-phase-a-candidate.csv"
    export_phase_a_candidate(candidate_path, record)
    loaded = load_phase_a_baseline(candidate_path)[0]

    assert record["pre_submit_state"] == "manual_challenge_handoff"
    assert record["final_status"] == "needs_review"
    assert record["handoff_reason"] == "captcha_detected"
    assert record["handoff_boundary"] == "post_fill_pre_action"
    assert "does not advance the Phase A gate" in record["notes"]
    assert loaded["phase_a_artifact_verified"] is True
    assert loaded["phase_a_exercise_verified"] is True
    assert loaded["official_posting_inspection_verified"] is True
    assert loaded["qualifies_for_dry_run_matrix"] is False
    assert loaded["phase_a_evidence_error"] is None


def test_manual_challenge_boundary_fails_closed_without_explicit_handoff_readiness(tmp_path):
    report = _report(outcome="manual_challenge_handoff")
    exercise = report["reports"][1]
    exercise.pop("manual_challenge_ready")
    exercise["review_items"] = [
        {
            "reason_code": "captcha_detected",
            "details": {"handoff_stage": "post_fill_pre_action"},
        }
    ]

    record = _build(tmp_path, report)
    candidate_path = tmp_path / "lever-phase-a-candidate.csv"
    export_phase_a_candidate(candidate_path, record)
    loaded = load_phase_a_baseline(candidate_path)[0]

    assert loaded["phase_a_artifact_verified"] is True
    assert loaded["phase_a_exercise_verified"] is False
    assert loaded["official_posting_inspection_verified"] is True
    assert loaded["qualifies_for_dry_run_matrix"] is False
    assert "manual-challenge handoff" in loaded["phase_a_evidence_error"]
