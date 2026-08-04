from pathlib import Path

from app.services.lever_phase_a_archive import verify_phase_a_external_archive


def _ready_row() -> dict:
    return {
        "run_id": "github-actions-30862050704-ready-d8-003",
        "source_reference": (
            "https://github.com/TheHighBrid/JobTomatik/actions/runs/30862050704"
        ),
        "artifact_path": "lever-phase-a-artifacts/D8-003/lever-phase-a-report.json",
        "artifact_sha256": "a" * 64,
        "pre_submit_state": "ready_to_submit",
        "final_status": "dry_run_passed",
    }


def test_ready_retention_row_requires_durable_external_archive(tmp_path: Path):
    baseline = tmp_path / "lever-phase-a-baseline.csv"
    baseline.write_text("run_id\n", encoding="utf-8")

    result = verify_phase_a_external_archive(
        _ready_row(),
        baseline_path=baseline,
    )

    assert result["required"] is True
    assert result["verified"] is False
    assert result["errors"] == ["missing_or_duplicate_source_manifest_row"]


def test_nonqualifying_ready_path_does_not_create_archive_requirement(tmp_path: Path):
    baseline = tmp_path / "lever-phase-a-baseline.csv"
    baseline.write_text("run_id\n", encoding="utf-8")
    row = _ready_row()
    row["pre_submit_state"] = "manual_challenge_handoff"
    row["final_status"] = "needs_review"

    result = verify_phase_a_external_archive(row, baseline_path=baseline)

    assert result == {
        "required": False,
        "verified": True,
        "archive_path": "",
        "errors": [],
    }
