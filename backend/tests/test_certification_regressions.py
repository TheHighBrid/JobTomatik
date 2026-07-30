import json
from pathlib import Path

from app.services.ats_lever import LEVER_ADAPTER_VERSION
from app.services.campaign_day_gates import build_day_12_22_report
from app.services.lever_pilot_ingestion import (
    load_phase_a_baseline,
    render_readiness_markdown,
)
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness
from scripts.export_lever_phase_a_record import (
    build_phase_a_candidate,
    export_phase_a_candidate,
)


ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "backend/evidence/lever-phase-a-baseline.csv"
READINESS_JSON_PATH = ROOT / "backend/evidence/lever-pilot-readiness.json"
READINESS_MARKDOWN_PATH = ROOT / "backend/evidence/lever-pilot-readiness.md"
GREENHOUSE_READINESS_JSON_PATH = (
    ROOT / "backend/evidence/greenhouse-phase-a-readiness.json"
)
CAMPAIGN_CHECKPOINT_JSON_PATH = (
    ROOT / "backend/evidence/campaign-days-12-22.json"
)
PHASE_1_WORKFLOW_PATH = ROOT / ".github/workflows/phase-1-release-gate.yml"
POSTING_ID = "12345678-1234-1234-1234-123456789abc"
LEVER_URL = f"https://jobs.eu.lever.co/exportco/{POSTING_ID}/apply"


def _report():
    return {
        "certification": "lever_supervised_live_dry_run",
        "final_submit_clicked": False,
        "passed": True,
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
                "passed": True,
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "certification_outcome": "ready_to_submit",
                "fields_filled": 8,
                "control_evidence_count": 8,
                "validation_errors": [],
                "review_items": [],
                "upload_evidence": [{"verification": "passed"}],
                "final_submit_clicked": False,
                "error": None,
            },
        ],
    }


def _greenhouse():
    return {
        "qualifying_dry_run_count": 30,
        "distinct_dry_run_employer_count": 30,
        "supervised_confirmed_count": 0,
        "gates": {
            "zero_duplicate_submissions": True,
            "all_uncertain_outcomes_remain_uncertain": True,
        },
    }


def test_committed_lever_readiness_artifacts_match_recalculated_baseline(tmp_path):
    readiness = read_lever_pilot_readiness(
        baseline_path=BASELINE_PATH,
        ledger_path=tmp_path / "missing-phase-b.jsonl",
    )

    assert readiness == json.loads(READINESS_JSON_PATH.read_text(encoding="utf-8"))
    assert render_readiness_markdown(readiness) == READINESS_MARKDOWN_PATH.read_text(
        encoding="utf-8"
    )


def test_committed_campaign_checkpoint_matches_current_readiness_inputs():
    lever = json.loads(READINESS_JSON_PATH.read_text(encoding="utf-8"))
    greenhouse = json.loads(
        GREENHOUSE_READINESS_JSON_PATH.read_text(encoding="utf-8")
    )
    expected = json.dumps(
        build_day_12_22_report(lever, greenhouse),
        indent=2,
        sort_keys=True,
    ) + "\n"

    assert expected == CAMPAIGN_CHECKPOINT_JSON_PATH.read_text(encoding="utf-8")


def test_phase_1_workflow_tracks_the_frozen_verifier_and_regression_contract():
    workflow = PHASE_1_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count("backend/app/services/lever_phase_a_evidence.py") >= 2
    assert workflow.count("backend/app/services/campaign_day_gates.py") >= 2
    assert workflow.count("backend/tests/test_certification_regressions.py") >= 3


def test_export_preserves_nested_report_path_when_output_directory_differs(tmp_path):
    report = _report()
    report_path = tmp_path / "lever-phase-a-artifacts" / "lever-report.json"
    report_path.parent.mkdir()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    output_path = tmp_path / "lever-phase-a-candidate.csv"

    record = build_phase_a_candidate(
        report,
        report_path=report_path,
        output_path=output_path,
        run_id="gha-123",
        operator="github-actions",
        source_reference="https://github.com/example/actions/runs/123",
        employer="Export Co",
        role="Risk Analyst",
        completed_at="2026-07-27T20:00:00+00:00",
    )
    export_phase_a_candidate(output_path, record)

    assert record["artifact_path"] == "lever-phase-a-artifacts/lever-report.json"
    loaded = load_phase_a_baseline(output_path)
    assert loaded[0]["qualifies_for_dry_run_matrix"] is True


def test_phase_b_days_and_promotion_require_phase_a_even_when_phase_b_is_green():
    gates = {
        "thirty_qualifying_dry_runs": False,
        "thirty_distinct_lever_sites": False,
        "global_and_eu_hosts_covered": False,
        "all_phase_a_records_have_successful_matching_inspection": False,
        "ten_supervised_confirmed_submissions": True,
        "zero_false_submitted_records": True,
        "zero_duplicate_submissions": True,
        "all_uncertain_outcomes_remain_uncertain": True,
        "all_success_evidence_independently_reviewed": True,
        "all_evidence_hashes_match_consumed_approvals": True,
        "explicit_separate_promotion_approval": True,
    }
    lever = {
        "summary": {
            "qualifying_dry_run_count": 0,
            "distinct_site_count": 0,
            "supervised_confirmed_count": 10,
            "regions_covered": [],
            "canonical_maturity": "dry_run",
            "promotion_ready": True,
            "gates": gates,
        }
    }

    report = build_day_12_22_report(lever, _greenhouse())
    checkpoints = {item["day"]: item for item in report["checkpoints"]}

    for day in (16, 17, 18, 19, 20, 21):
        assert checkpoints[day]["passed"] is False
        assert "complete Lever Phase A" in checkpoints[day]["blockers"]
