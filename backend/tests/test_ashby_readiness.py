import json

from app.services.ashby_readiness import build_ashby_certification_dossier


POSTING_A = "7458d4e9-da2e-47bd-98cb-adfda43d42b2"
POSTING_B = "8a429823-5135-4bd5-b093-90b1374150d4"


def _junit(path, *, tests=3, failures=0, errors=0):
    path.write_text(
        f'<testsuite tests="{tests}" failures="{failures}" errors="{errors}" skipped="0"></testsuite>',
        encoding="utf-8",
    )


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_dossier_credits_only_dry_run_boundary(tmp_path):
    fixture = tmp_path / "fixture.xml"
    handoff = tmp_path / "handoff.xml"
    live = tmp_path / "live.json"
    synthetic = tmp_path / "synthetic.json"
    _junit(fixture, tests=12)
    _junit(handoff, tests=4)
    _write_json(
        live,
        {
            "passed": True,
            "final_submit_clicked": False,
            "url_count": 2,
            "reports": [
                {
                    "mode": "inspect",
                    "passed": True,
                    "url": f"https://jobs.ashbyhq.com/ashby/{POSTING_A}/application",
                    "surface_url": f"https://jobs.ashbyhq.com/ashby/{POSTING_A}/application",
                    "official_form_definition_status": "not_configured",
                    "final_submit_clicked": False,
                },
                {
                    "mode": "inspect",
                    "passed": True,
                    "url": f"https://jobs.ashbyhq.com/ashby/{POSTING_B}/application",
                    "surface_url": f"https://jobs.ashbyhq.com/ashby/{POSTING_B}/application",
                    "official_form_definition_status": "not_configured",
                    "final_submit_clicked": False,
                },
            ],
        },
    )
    _write_json(
        synthetic,
        {
            "passed": True,
            "final_submit_clicked": False,
            "url_count": 1,
            "reports": [
                {
                    "mode": "inspect",
                    "passed": True,
                    "url": f"https://jobs.ashbyhq.com/ashby/{POSTING_A}/application",
                    "surface_url": f"https://jobs.ashbyhq.com/ashby/{POSTING_A}/application",
                    "official_form_definition_status": "not_configured",
                    "final_submit_clicked": False,
                },
                {
                    "mode": "exercise",
                    "passed": True,
                    "url": f"https://jobs.ashbyhq.com/ashby/{POSTING_A}/application",
                    "certification_outcome": "ready_to_submit",
                    "upload_evidence": [{"verification": "passed"}],
                    "final_submit_clicked": False,
                },
            ],
        },
    )

    dossier = build_ashby_certification_dossier(
        fixture_junit=fixture,
        handoff_junit=handoff,
        live_smoke_json=live,
        synthetic_live_json=synthetic,
        source_commit="abc123",
        generated_at="2026-08-23T12:00:00Z",
        adapter_version="1.1.0",
    )

    assert dossier["maturity"] == "dry_run"
    assert dossier["readiness"]["dry_run_certification_ready"] is True
    assert dossier["readiness"]["human_reviewed_submit_ready"] is False
    assert dossier["readiness"]["autonomous_ready"] is False
    assert dossier["readiness"]["promotion_ready"] is False
    assert dossier["safety"]["credited_real_submissions"] == 0
    assert dossier["safety"]["final_submit_clicked"] is False
    assert dossier["synthetic_live_dry_run"]["duplicate_targets_within_lane"] == 0
    assert dossier["synthetic_live_dry_run"]["verified_upload_count"] == 1
    assert dossier["coverage"]["distinct_current_public_targets"] == 2
    assert (
        "credentialed_live_form_definition_validation_not_retained"
        in dossier["readiness"]["promotion_blockers"]
    )
    assert all(item["sha256"] for item in dossier["inputs"])


def test_dossier_fails_closed_when_locked_input_is_not_safe(tmp_path):
    fixture = tmp_path / "fixture.xml"
    handoff = tmp_path / "handoff.xml"
    live = tmp_path / "live.json"
    synthetic = tmp_path / "synthetic.json"
    _junit(fixture, tests=12)
    _junit(handoff, tests=4, failures=1)
    _write_json(
        live,
        {
            "passed": True,
            "final_submit_clicked": False,
            "url_count": 1,
            "reports": [
                {
                    "mode": "inspect",
                    "passed": True,
                    "url": f"https://jobs.ashbyhq.com/ashby/{POSTING_A}/application",
                    "official_form_definition_status": "error",
                    "final_submit_clicked": False,
                }
            ],
        },
    )
    _write_json(
        synthetic,
        {
            "passed": False,
            "final_submit_clicked": True,
            "url_count": 1,
            "reports": [
                {
                    "mode": "exercise",
                    "passed": False,
                    "url": f"https://jobs.ashbyhq.com/ashby/{POSTING_A}/application",
                    "upload_evidence": [],
                    "final_submit_clicked": True,
                }
            ],
        },
    )

    dossier = build_ashby_certification_dossier(
        fixture_junit=fixture,
        handoff_junit=handoff,
        live_smoke_json=live,
        synthetic_live_json=synthetic,
        source_commit="abc123",
        generated_at="2026-08-23T12:00:00Z",
        adapter_version="1.1.0",
    )

    blockers = dossier["readiness"]["dry_run_blockers"]
    assert dossier["readiness"]["dry_run_certification_ready"] is False
    assert "resumable_handoff_matrix_failed" in blockers
    assert "synthetic_live_exercise_failed" in blockers
    assert "no_verified_live_form_upload" in blockers
    assert "credentialed_form_definition_validation_error" in blockers
    assert dossier["readiness"]["promotion_ready"] is False
