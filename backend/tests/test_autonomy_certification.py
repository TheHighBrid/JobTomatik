import pytest

from app.services.autonomy_certification import (
    _live_dry_run_status,
    build_autonomy_certification_manifest,
)
from app.services.ats_maturity import AUTONOMY_RELEASE_GATES, HUMAN_REVIEWED_RELEASE_GATES


def _adapter_with_synthetic_live_exercise(status: str):
    return {
        "maturity": "dry_run",
        "live_certification": {
            "synthetic_live_full_form_exercise": status,
            "fixture_verified_resume_upload": True,
            "final_submit_clicked": False,
        },
    }


def test_autonomy_certification_manifest_tracks_current_blockers():
    manifest = build_autonomy_certification_manifest()

    assert manifest["framework_version"] == "autonomy_certification_v1"
    assert manifest["target_maturity"] == "certified_autonomous"
    assert manifest["current_runtime"]["real_submission_enabled"] is False
    assert manifest["current_runtime"]["autopilot_enabled"] is False
    assert manifest["ready_adapters"] == []
    assert manifest["remaining_adapter_count"] == len(manifest["adapters"])
    assert manifest["invariants"]["does_not_enable_real_submission"] is True

    greenhouse = next(item for item in manifest["adapters"] if item["name"] == "greenhouse")
    assert greenhouse["current_maturity"] == "dry_run"
    assert greenhouse["stages"]["live_dry_run_evidence"]["passed"] is True
    assert greenhouse["stages"]["human_reviewed_real_submission"]["passed"] is False
    assert greenhouse["stages"]["autonomous_real_submission"]["passed"] is False
    assert greenhouse["ready_for_autonomous_release"] is False
    assert greenhouse["next_blockers"] == [
        "human_reviewed_real_submission",
        "autonomous_real_submission",
    ]


@pytest.mark.parametrize(
    "status",
    [
        "not_reached_due_to_pre_form_datadome",
        "not_reached_due_to_account_boundary",
    ],
)
def test_unreached_synthetic_live_exercises_remain_certification_blockers(status):
    stage = _live_dry_run_status(_adapter_with_synthetic_live_exercise(status))

    assert stage["passed"] is False
    assert stage["checks"]["boundary_or_synthetic_exercise_present"] is False
    assert "boundary_or_synthetic_exercise_present" in stage["missing"]


@pytest.mark.parametrize("status", ["certified", "reached"])
def test_explicit_synthetic_live_exercise_evidence_clears_boundary_check(status):
    stage = _live_dry_run_status(_adapter_with_synthetic_live_exercise(status))

    assert stage["passed"] is True
    assert stage["checks"]["boundary_or_synthetic_exercise_present"] is True
    assert stage["missing"] == []


def test_autonomy_certification_endpoint(client):
    response = client.get("/api/system/autonomy-certification")

    assert response.status_code == 200
    payload = response.json()
    stage_ids = {stage["id"] for stage in payload["stages"]}
    assert {
        "live_dry_run_evidence",
        "human_reviewed_real_submission",
        "autonomous_real_submission",
    }.issubset(stage_ids)
    human_stage = next(
        stage for stage in payload["stages"] if stage["id"] == "human_reviewed_real_submission"
    )
    autonomy_stage = next(
        stage for stage in payload["stages"] if stage["id"] == "autonomous_real_submission"
    )
    assert tuple(human_stage["checks"]) == HUMAN_REVIEWED_RELEASE_GATES
    assert tuple(autonomy_stage["checks"]) == AUTONOMY_RELEASE_GATES
