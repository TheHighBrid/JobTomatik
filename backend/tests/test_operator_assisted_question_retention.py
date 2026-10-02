from app.services import form_filler_handoff
from app.services.operator_assisted_handoff_integration import operator_prepare_scope
from app.services.operator_assisted_question_retention import (
    install_operator_assisted_question_retention,
    summarize_operator_question_retention_result,
)


def _ambiguous_result(*, with_snapshot: bool = False):
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
            "browser_session_id": "sensitive-runtime-detail",
            "current_url": "https://jobs.lever.co/example/posting/apply",
            "current_fingerprint": "abc123",
        }
    return result


def test_ambiguous_question_is_not_globally_resumable():
    install_operator_assisted_question_retention()
    assert form_filler_handoff._resumable_boundary(_ambiguous_result()) is False


def test_operator_prepare_scope_does_not_retain_ambiguous_question_page():
    install_operator_assisted_question_retention()

    with operator_prepare_scope({"identity_hash": "b" * 64, "verified": True}):
        assert form_filler_handoff._resumable_boundary(_ambiguous_result()) is False

    assert form_filler_handoff._resumable_boundary(_ambiguous_result()) is False


def test_operator_question_receipt_requires_fresh_reprepare_and_releases_previous_tab():
    result = summarize_operator_question_retention_result(
        _ambiguous_result(with_snapshot=True)
    )

    assert "handoff_snapshot" not in result
    assert result["operator_question_review_page_retained"] is False
    assert result["operator_question_review_handoff_created"] is False
    assert result["requires_answer_policy_review"] is True
    assert result["requires_fresh_reprepare_after_answer_policy"] is True
    assert result["operator_question_reprepare_releases_previous_tab"] is True
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
