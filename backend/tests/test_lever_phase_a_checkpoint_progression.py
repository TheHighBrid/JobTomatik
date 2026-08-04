from pathlib import Path

from scripts.verify_lever_phase_a_checkpoint import verify_checkpoint


def test_committed_phase_a_checkpoint_supports_monotonic_progress(tmp_path: Path):
    result = verify_checkpoint(
        evidence_root=Path("evidence"),
        output_root=tmp_path / "verified-checkpoint",
    )

    assert result["passed"] is True
    assert result["qualifying_dry_run_count"] == 30
    assert result["distinct_site_count"] == result["qualifying_dry_run_count"]
    assert result["record_count"] == result["qualifying_dry_run_count"] + 1
    assert result["source_receipt_count"] == result["record_count"] + 1
    assert result["manual_challenge_boundary_count"] == 1
    assert result["phase_a_target_reached"] is (
        result["qualifying_dry_run_count"] == 30
    )
    assert result["safety"] == {
        "final_submit_clicked": False,
        "maturity_promoted": False,
        "real_submission_enabled": False,
    }
