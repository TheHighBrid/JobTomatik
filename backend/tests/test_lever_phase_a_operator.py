from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.ats_lever import LEVER_ADAPTER_VERSION
from app.services.handoff_session import decrypt_handoff_secret
from app.services.lever_phase_a_operator import (
    FROZEN_DAY8_CORPUS_SHA256,
    LeverPhaseAOperatorError,
    build_phase_a_report,
    build_resumed_exercise,
    load_locked_target,
    transient_handoff_session,
    write_report,
)
from app.services import retained_browser_operator


ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = ROOT / "backend" / "evidence" / "lever-phase-a-target-corpus"
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


def _verified_handoff() -> dict:
    return {
        "challenge_cleared": True,
        "verification_method": "captcha_response_state",
        "target_verification": {
            "verified": True,
            "expected_posting_id": POSTING_ID,
            "observed_posting_id": POSTING_ID,
        },
    }


def _clean_submit_guard() -> dict:
    return {
        "installed": True,
        "blocked_clicks": 0,
        "blocked_submits": 0,
    }


def _snapshot(endpoint: str = "http://127.0.0.1:45678") -> dict:
    return {
        "browser_provider": "local_cdp",
        "browser_endpoint": endpoint,
        "browser_node_id": "test-node",
        "browser_process_id": 1234,
        "browser_profile_path": "/tmp/persistent-profile",
        "browser_session_id": str(uuid4()),
        "current_url": URL,
        "current_fingerprint": "fingerprint",
        "metadata": {"fields_filled": 5},
    }


def _target_metadata() -> dict:
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": LEVER_ADAPTER_VERSION,
        "site": "acme",
        "posting_id": POSTING_ID,
        "region": "global",
    }


def test_load_locked_target_validates_the_exact_frozen_corpus() -> None:
    target = load_locked_target("D8-001", CORPUS_ROOT)

    assert target["review_id"] == "D8-001"
    assert target["active"] is True
    assert target["viable"] is True
    assert target["corpus_sha256"] == FROZEN_DAY8_CORPUS_SHA256


def test_replaced_or_mutated_corpus_is_rejected(tmp_path: Path) -> None:
    replacement = tmp_path / "replacement-corpus"
    shutil.copytree(CORPUS_ROOT, replacement)
    first_part = replacement / "part-01.csv"
    first_part.write_text(
        first_part.read_text(encoding="utf-8").replace(
            "Veeva Systems", "Veeva SystemsX", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        load_locked_target("D8-001", replacement)


def test_transient_session_encrypts_local_cdp_endpoint_and_locks_target() -> None:
    endpoint = "http://127.0.0.1:45678"
    session = transient_handoff_session(
        _snapshot(endpoint),
        reason_code="captcha_detected",
        target_metadata=_target_metadata(),
    )

    assert decrypt_handoff_secret(session.encrypted_browser_endpoint) == endpoint
    assert session.challenge_type == "captcha"
    assert session.handoff_metadata["phase_a_interactive"] is True
    assert session.handoff_metadata["supervised_target"]["posting_id"] == POSTING_ID
    assert endpoint not in str(session.handoff_metadata)


def test_transient_session_rejects_nonlocal_cdp_endpoint() -> None:
    with pytest.raises(LeverPhaseAOperatorError, match="127.0.0.1"):
        transient_handoff_session(
            _snapshot("http://192.0.2.25:9222"),
            reason_code="captcha_detected",
            target_metadata=_target_metadata(),
        )


def test_resumed_handoff_builds_report_ready_for_external_retention(
    tmp_path: Path,
) -> None:
    exercise = build_resumed_exercise(
        url=URL,
        initial_result=_initial_handoff(),
        resumed_result=_resumed_ready(),
        certification_metadata={
            "synthetic_profile": True,
            "review_id": "D8-001",
        },
        handoff_verification=_verified_handoff(),
        submit_guard=_clean_submit_guard(),
    )
    report = build_phase_a_report(_inspection(), exercise)
    report_path = tmp_path / "lever-phase-a-interactive-report.json"
    digest = write_report(report_path, report)
    retained = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["passed"] is True
    assert report["final_submit_clicked"] is False
    assert exercise["certification_outcome"] == "ready_to_submit"
    assert exercise["upload_evidence"][0]["verification"] == "passed"
    assert len(digest) == 64
    assert retained == report


def test_unverified_or_missing_handoff_prevents_phase_a_success() -> None:
    exercise = build_resumed_exercise(
        url=URL,
        initial_result=_initial_handoff(),
        resumed_result=_resumed_ready(),
        certification_metadata={"synthetic_profile": True},
        handoff_verification={},
        submit_guard=_clean_submit_guard(),
    )

    assert exercise["passed"] is False
    assert exercise["error"] == "The retained browser handoff was not independently verified."


def test_any_submit_log_prevents_phase_a_success() -> None:
    resumed = _resumed_ready()
    resumed["log"].append({"action": "ats_submit_clicked"})
    exercise = build_resumed_exercise(
        url=URL,
        initial_result=_initial_handoff(),
        resumed_result=resumed,
        certification_metadata={"synthetic_profile": True},
        handoff_verification=_verified_handoff(),
        submit_guard=_clean_submit_guard(),
    )
    report = build_phase_a_report(_inspection(), exercise)

    assert exercise["passed"] is False
    assert exercise["final_submit_clicked"] is True
    assert report["passed"] is False
    assert report["final_submit_clicked"] is True


def test_missing_submit_guard_after_handoff_prevents_phase_a_success() -> None:
    exercise = build_resumed_exercise(
        url=URL,
        initial_result=_initial_handoff(),
        resumed_result=_resumed_ready(),
        certification_metadata={"synthetic_profile": True},
        handoff_verification=_verified_handoff(),
        submit_guard={"installed": False},
    )

    assert exercise["passed"] is False
    assert exercise["certification_outcome"] == "failed"
    assert exercise["error"] == "The submit guard was not present after human verification."


def test_intercepted_submit_intent_prevents_phase_a_success() -> None:
    exercise = build_resumed_exercise(
        url=URL,
        initial_result=_initial_handoff(),
        resumed_result=_resumed_ready(),
        certification_metadata={"synthetic_profile": True},
        handoff_verification=_verified_handoff(),
        submit_guard={
            "installed": True,
            "blocked_clicks": 1,
            "blocked_submits": 0,
        },
    )

    assert exercise["passed"] is False
    assert exercise["final_submit_clicked"] is False
    assert exercise["error"] == "The submit guard intercepted an operator submit attempt."


def test_cleanup_removes_transient_state_but_preserves_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_root = tmp_path / "handoff-sessions"
    profile = tmp_path / "persistent-profile"
    profile.mkdir()
    session_id = str(uuid4())
    transient = storage_root / session_id
    transient.mkdir(parents=True)
    for name in ("handoff.png", "page.html", "storage-state.json", "chromium.log"):
        (transient / name).write_text("sensitive transient state", encoding="utf-8")
    session = SimpleNamespace(
        browser_session_id=session_id,
        browser_profile_path=str(profile),
    )
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(storage_root))
    monkeypatch.setattr(
        retained_browser_operator,
        "terminate_retained_browser",
        lambda _session: True,
    )

    assert retained_browser_operator.terminate_and_cleanup_retained_browser(session) is True
    assert not transient.exists()
    assert profile.exists()


def test_interactive_runner_uses_public_browser_helpers_and_submit_guards() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_lever_phase_a_handoff.py"
    ).read_text(encoding="utf-8")

    assert "document.addEventListener('click', clickHandler, true)" in source
    assert "document.addEventListener('submit', submitHandler, true)" in source
    assert "evaluate_retained_browser" in source
    assert "terminate_and_cleanup_retained_browser" in source
    assert "_connect_local_cdp" not in source
    assert 'os.environ["ALLOW_REAL_APPLICATION_SUBMIT"] = "false"' in source
    assert 'os.environ["AUTOPILOT_ENABLED"] = "false"' in source
    assert "dry_run=True" in source
    assert "local-sha256:" not in source
    assert "build_phase_a_candidate" not in source
