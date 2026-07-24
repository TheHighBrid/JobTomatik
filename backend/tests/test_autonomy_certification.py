from app.services.autonomy_certification import build_autonomy_certification_manifest
from app.services.ats_maturity import AUTONOMY_RELEASE_GATES, HUMAN_REVIEWED_RELEASE_GATES


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
