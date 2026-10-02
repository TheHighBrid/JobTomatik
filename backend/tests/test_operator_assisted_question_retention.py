from app.services import form_filler_handoff
from app.services.operator_assisted_handoff_integration import operator_prepare_scope
from app.services import operator_assisted_question_retention as retention
from app.services.operator_assisted_question_retention import (
    QUESTION_REVIEW_RETENTION_SECONDS,
    cleanup_operator_question_review_browser,
    install_operator_assisted_question_retention,
    summarize_operator_question_retention_result,
)


def _ambiguous_result(*, with_snapshot: bool = False, session_id: str = "sensitive-runtime-detail"):
    result = {
        "success": False,
        "dry_run": True,
        "requires_manual_review": True,
        "error": "Required application fields need review before the ATS flow can continue.",
        "review_items": [
            {
                "reason_code": "ambiguous_question",
                "summary": "Approved answer required for an employer question.",
                "details": {"required": True, "control_type": "text"},
            }
        ],
        "application_url": "https://jobs.lever.co/example/posting/apply",
    }
    if with_snapshot:
        result["handoff_snapshot"] = {
            "browser_provider": "local_cdp",
            "browser_endpoint": "http://127.0.0.1:9222",
            "browser_session_id": session_id,
            "browser_node_id": "worker-one",
            "browser_process_id": 24680,
            "current_url": "https://jobs.lever.co/example/posting/apply",
            "current_fingerprint": "abc123",
        }
    return result


def test_ambiguous_question_is_not_globally_resumable():
    install_operator_assisted_question_retention()

    assert form_filler_handoff._resumable_boundary(_ambiguous_result()) is False


def test_operator_prepare_scope_retains_ambiguous_question_page():
    install_operator_assisted_question_retention()

    with operator_prepare_scope({"identity_hash": "b" * 64, "verified": True}):
        assert form_filler_handoff._resumable_boundary(_ambiguous_result()) is True

    assert form_filler_handoff._resumable_boundary(_ambiguous_result()) is False


def test_operator_question_receipt_strips_raw_browser_snapshot_and_keeps_no_submit_flags():
    result = summarize_operator_question_retention_result(
        _ambiguous_result(with_snapshot=True)
    )

    assert "handoff_snapshot" not in result
    assert result["operator_question_review_page_retained"] is True
    assert result["operator_question_review_handoff_created"] is False
    assert result["requires_answer_policy_review"] is True
    assert result["requires_fresh_reprepare_after_answer_policy"] is True
    assert result["operator_question_review_url"].startswith("https://jobs.lever.co/")
    assert result["operator_question_review_browser_provider"] == "local_cdp"
    assert result["automated_submission_authorized"] is False
    assert result["final_submit_clicked_by_jobtomatik"] is False
    assert "sensitive-runtime-detail" not in repr(result)


def test_non_question_result_is_not_rewritten():
    result = {
        "success": False,
        "requires_manual_review": True,
        "review_items": [{"reason_code": "captcha_detected"}],
        "handoff_snapshot": {"browser_session_id": "keep-normal-handoff-data"},
    }

    normalized = summarize_operator_question_retention_result(result)

    assert normalized["handoff_snapshot"] == result["handoff_snapshot"]
    assert "operator_question_review_page_retained" not in normalized


def test_question_retention_removes_snapshot_artifacts_and_schedules_bounded_cleanup(
    tmp_path, monkeypatch
):
    session_id = "12345678-1234-5678-1234-567812345678"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    for filename in ("storage-state.json", "page.html", "handoff.png"):
        (session_dir / filename).write_text("sensitive", encoding="utf-8")
    (session_dir / "chromium.log").write_text("runtime", encoding="utf-8")
    scheduled = []
    monkeypatch.setattr(retention, "handoff_storage_root", lambda: tmp_path)

    normalized = summarize_operator_question_retention_result(
        _ambiguous_result(with_snapshot=True, session_id=session_id),
        schedule_cleanup=lambda handle, countdown: scheduled.append((handle, countdown)),
    )

    assert scheduled == [(
        {
            "browser_provider": "local_cdp",
            "browser_session_id": session_id,
            "browser_node_id": "worker-one",
            "browser_process_id": 24680,
        },
        QUESTION_REVIEW_RETENTION_SECONDS,
    )]
    assert not (session_dir / "storage-state.json").exists()
    assert not (session_dir / "page.html").exists()
    assert not (session_dir / "handoff.png").exists()
    assert (session_dir / "chromium.log").exists()
    assert normalized["operator_question_review_cleanup_scheduled"] is True
    assert normalized["operator_question_review_retained_until"]
    assert "browser_endpoint" not in repr(scheduled)


def test_question_cleanup_uses_retained_runtime_handle(monkeypatch):
    captured = []
    monkeypatch.setattr(
        retention,
        "terminate_and_cleanup_retained_browser",
        lambda session: captured.append(session) or True,
    )

    cleaned = cleanup_operator_question_review_browser(
        {
            "browser_provider": "local_cdp",
            "browser_session_id": "12345678-1234-5678-1234-567812345678",
            "browser_node_id": "worker-one",
            "browser_process_id": 24680,
        }
    )

    assert cleaned is True
    assert captured[0].browser_process_id == 24680
    assert captured[0].browser_session_id == "12345678-1234-5678-1234-567812345678"
