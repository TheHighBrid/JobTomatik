import copy
import json
from pathlib import Path

import pytest

from app.services.campaign_day_gates import build_day_12_22_report
from scripts.build_lever_phase_b_launch import (
    LeverPhaseBLaunchError,
    _json_bytes,
    _validate_selection,
    build_launch,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = BACKEND_ROOT / "evidence"
SELECTION = EVIDENCE / "lever-phase-b-user-selection-2026-08-04.json"
BASELINE = EVIDENCE / "lever-phase-a-baseline.csv"
LAUNCH = EVIDENCE / "lever-phase-b-launch.json"


def _day(report, day):
    return next(item for item in report["checkpoints"] if item["day"] == day)


def test_committed_day15_launch_artifacts_are_reproducible():
    launch, dossiers = build_launch(
        evidence_root=EVIDENCE,
        selection_path=SELECTION,
        baseline_path=BASELINE,
    )

    assert _json_bytes(launch) == LAUNCH.read_bytes()
    assert len(launch["applications"]) == 2
    assert {
        item["target"]["employer"] for item in launch["applications"]
    } == {"Cin7", "PocketHealth"}

    for relative_path, payload in dossiers.items():
        assert (EVIDENCE / relative_path).read_bytes() == payload

    for application in launch["applications"]:
        assert application["selected_by_user"] is True
        assert application["dry_preview"]["passed"] is True
        assert application["dry_preview"]["outcome"] == "ready_to_submit"
        assert application["dry_preview"]["final_submit_clicked"] is False
        assert application["dossier"]["read_only"] is True
        assert application["dossier"]["one_time_approval_required"] is True


def test_actual_day15_evidence_completes_only_the_launch_dossier_gate():
    lever = json.loads(
        (EVIDENCE / "lever-pilot-readiness.json").read_text(encoding="utf-8")
    )
    greenhouse = json.loads(
        (EVIDENCE / "greenhouse-phase-a-readiness.json").read_text(
            encoding="utf-8"
        )
    )
    launch = json.loads(LAUNCH.read_text(encoding="utf-8"))

    report = build_day_12_22_report(
        lever,
        greenhouse,
        launch,
        lever_phase_b_artifact_root=EVIDENCE,
    )

    day15 = _day(report, 15)
    assert day15["passed"] is True
    assert day15["facts"]["selected_application_count"] == 2
    assert day15["facts"]["approval_dossier_count"] == 2
    assert day15["facts"]["dry_preview_count"] == 2
    assert day15["facts"]["ready_application_count"] == 2
    assert day15["facts"]["invalid_dossier_count"] == 0

    day16 = _day(report, 16)
    assert day16["passed"] is False
    assert day16["facts"]["safe_confirmed_submissions"] == 0
    assert report["safety"] == {
        "approval_issued": False,
        "browser_opened": False,
        "final_submit_clicked": False,
        "maturity_promoted": False,
        "network_contacted": False,
        "submission_queued": False,
    }


def test_selection_receipt_cannot_authorize_submit_or_promotion():
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))

    for field in (
        "authorize_final_submit",
        "authorize_supervised_submission",
        "authorize_adapter_promotion",
    ):
        unsafe = copy.deepcopy(selection)
        unsafe["requested_action"][field] = True
        with pytest.raises(LeverPhaseBLaunchError, match=field):
            _validate_selection(unsafe)
