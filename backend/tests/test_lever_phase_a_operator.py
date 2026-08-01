from __future__ import annotations

import csv
from pathlib import Path

from app.services.ats_lever import LEVER_ADAPTER_VERSION
from app.services.handoff_session import decrypt_handoff_secret
from app.services.lever_phase_a_operator import (
    build_phase_a_report,
    build_resumed_exercise,
    load_locked_target,
    transient_handoff_session,
    write_report,
)
from app.services.lever_pilot_ingestion import load_phase_a_baseline
from scripts.export_lever_phase_a_record import (
    build_phase_a_candidate,
    export_phase_a_candidate,
)


POSTING_ID = "11111111-2222-3333-4444-555555555555"
URL = f"https://jobs.lever.co/acme/{POSTING_ID}/apply"


def _inspection() -> dict:
    return {
        "url": URL,
        "mode": "inspect",
        "passed": True,
        "final_submit_clicked": False,
        "adapter": "lever",
        "adapter_version": LEVER_ADAPTER_VERSION,
        "dom": {
            "visible_control_count": 7,
            "required_control_count": 5,
        },
    }


def _initial_handoff() -> dict:
    return {
        "success": False,
        "ready_to_submit": False,
        "requires_manual_review": True,
        "ats_adapter": "lever",
        "ats_adapter_version": LEVER_ADAPTER_VERSION,
        "fields_filled": 5,
        "steps_completed": 1,
        "log": [{"action": "ats_manual_challenge_ready"}],
        "review_items": [
            {
                "reason_code": "captcha_detected",
                "summary": "Human verification required.",
                "details": {"handoff_stage": "post_fill_pre_action"},
            }
        ],
        "validation_errors": [],
        "upload_evidence": [
            {"filename": "synthetic.pdf", "verification": "passed"}
        ],
        "step_evidence": [{"action": "ats_step_filled", "step": 1}],
        "control_evidence": [
            {"control_id": "name", "verification": "passed"},
            {"control_id": "email", "verification": "passed"},
        ],
    }


def _resumed_ready() -> dict:
    return {
        "success": True,
        "ready_to_submit": True,
        "requires_manual_review": False,
        "ats_adapter": "lever",
        "ats_adapter_version": LEVER_ADAPTER_VERSION,
        "fields_filled": 5,
        "steps_completed": 1,
        "log": [{"action": "ats_final_submit_ready", "submit_clicked": False}],
        "review_items": [],
        "validation_errors": [],
        "upload_evidence": [
            {"filename": "synthetic.pdf", "verification": "passed"}
        ],
        "step_evidence": [{"action": "ats_final_submit_ready", "step": 1}],
        "control_evidence": [
            {"control_id": "name", "verification": "passed"},
            {"control_id": "email", "verification": "passed"},
        ],
        "error": None,
    }


def test_load_locked_target_requires_one_exact_viable_corpus_row(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    path = corpus / "part-01.csv"
    fieldnames = [
        "review_id",
        "employer",
        "role",
        "site",
        "posting_id",
        "region",
        "canonical_application_url",
        "active",
        "viable",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "review_id": "D8-001",
                "employer": "Acme",
                "role": "Engineer",
                "site": "acme",
                "posting_id": POSTING_ID,
                "region": "global",
                "canonical_application_url": URL,
                "active": "True",
                "viable": "True",
            }
        )

    target = load_locked_target("D8-001", corpus)

    assert target["employer"] == "Acme"
    assert target["canonical_application_url"] == URL
    assert target["corpus_path"].endswith("part-01.csv")


def test_transient_session_encrypts_cdp_endpoint_and_locks_target() -> None:
    endpoint = "http://127.0.0.1:45678"
    session = transient_handoff_session(
        {
            "browser_provider": "local_cdp",
            "browser_endpoint": endpoint,
            "browser_node_id": "test-node",
            "browser_process_id": 1234,
            "browser_profile_path": "/tmp/profile",
            "browser_session_id": "session-1",
            "current_url": URL,
            "current_fingerprint": "fingerprint",
            "metadata": {"fields_filled": 5},
        },
        reason_code="captcha_detected",
        target_metadata={
            "platform": "lever",
            "adapter": "lever",
            "adapter_version": LEVER_ADAPTER_VERSION,
            "site": "acme",
            "posting_id": POSTING_ID,
            "region": "global",
        },
    )

    assert decrypt_handoff_secret(session.encrypted_browser_endpoint) == endpoint
    assert session.challenge_type == "captcha"
    assert session.handoff_metadata["phase_a_interactive"] is True
    assert session.handoff_metadata["supervised_target"]["posting_id"] == POSTING_ID
    assert endpoint not in str(session.handoff_metadata)


def test_resumed_handoff_builds_a_qualifying_retained_candidate(tmp_path: Path) -> None:
    exercise = build_resumed_exercise(
        url=URL,
        initial_result=_initial_handoff(),
        resumed_result=_resumed_ready(),
        certification_metadata={"synthetic_profile": True},
        handoff_verification={
            "challenge_cleared": True,
            "verification_method": "captcha_response_state",
        },
        submit_guard={
            "installed": True,
            "blocked_clicks": 0,
            "blocked_submits": 0,
        },
    )
    report = build_phase_a_report(_inspection(), exercise)
    report_path = tmp_path / "interactive-report.json"
    candidate_path = tmp_path / "candidate.csv"
    digest = write_report(report_path, report)

    record = build_phase_a_candidate(
        report,
        report_path=report_path,
        output_path=candidate_path,
        run_id=f"local-d8-001-{digest[:16]}",
        operator="test-operator",
        source_reference=f"local-sha256:{digest}",
        employer="Acme",
        role="Engineer",
    )
    export_phase_a_candidate(candidate_path, record)
    loaded = load_phase_a_baseline(candidate_path)

    assert report["passed"] is True
    assert exercise["certification_outcome"] == "ready_to_submit"
    assert exercise["final_submit_clicked"] is False
    assert exercise["upload_evidence"][0]["verification"] == "passed"
    assert len(loaded) == 1
    assert loaded[0]["phase_a_artifact_verified"] is True
    assert loaded[0]["official_posting_inspection_verified"] is True
    assert loaded[0]["phase_a_exercise_verified"] is True
    assert loaded[0]["qualifies_for_dry_run_matrix"] is True


def test_any_submit_log_prevents_phase_a_success() -> None:
    resumed = _resumed_ready()
    resumed["log"].append({"action": "ats_submit_clicked"})
    exercise = build_resumed_exercise(
        url=URL,
        initial_result=_initial_handoff(),
        resumed_result=resumed,
        certification_metadata={"synthetic_profile": True},
    )
    report = build_phase_a_report(_inspection(), exercise)

    assert exercise["passed"] is False
    assert exercise["final_submit_clicked"] is True
    assert report["passed"] is False
    assert report["final_submit_clicked"] is True


def test_interactive_runner_installs_click_and_submit_guards() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_lever_phase_a_handoff.py"
    ).read_text(encoding="utf-8")

    assert "document.addEventListener('click', clickHandler, true)" in source
    assert "document.addEventListener('submit', submitHandler, true)" in source
    assert 'os.environ["ALLOW_REAL_APPLICATION_SUBMIT"] = "false"' in source
    assert 'os.environ["AUTOPILOT_ENABLED"] = "false"' in source
    assert "dry_run=True" in source
