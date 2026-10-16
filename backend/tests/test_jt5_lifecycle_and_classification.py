"""JT5 claim/finalize helpers and browser-result classification."""
from app.tasks.jt5_execution import _classify_browser_result


def test_classify_confirmed_requires_evidence():
    assert (
        _classify_browser_result(
            {
                "success": True,
                "submitted_at": "2026-10-11T12:00:00",
                "submission_confirmed": True,
                "confirmation_evidence": [{"is_sufficient": True}],
            }
        )
        == "confirmed"
    )
    assert (
        _classify_browser_result(
            {
                "success": True,
                "confirmation_evidence": [{"is_sufficient": True}],
            }
        )
        == "confirmed"
    )


def test_classify_dry_run_success_is_not_confirmed():
    assert (
        _classify_browser_result({"success": True, "dry_run": True})
        == "submission_uncertain"
    )


def test_classify_manual_review_before_submit():
    assert (
        _classify_browser_result(
            {
                "success": False,
                "requires_manual_review": True,
                "log": [{"action": "missing_field"}],
            }
        )
        == "submission_uncertain"
    )


def test_classify_submit_clicked_without_receipt_is_uncertain():
    assert (
        _classify_browser_result(
            {
                "success": False,
                "requires_manual_review": True,
                "log": [{"action": "submit clicked"}],
            }
        )
        == "submission_uncertain"
    )


def test_classify_plain_error_pre_submit():
    assert (
        _classify_browser_result({"success": False, "error": "timeout"})
        == "submission_uncertain"
    )


def test_explicit_pre_submit_proof_allows_safe_failure():
    assert _classify_browser_result({
        "success": False,
        "final_submit_attempted": False,
        "pre_submit_failure_verified": True,
    }) == "failed_pre_submit"
