"""JT5 browser-result classification must never infer a safe retry from silence."""
import pytest

from app.tasks.jt5_execution import _classify_browser_result


@pytest.mark.parametrize("result", [
    {"success": False, "error": "timeout"},
    {"success": False, "requires_manual_review": True, "error": "captcha"},
    {"success": False, "error": "connection reset", "submitted_at": None},
    {"success": True, "submitted_at": "2026-10-11T00:00:00"},
    {"success": True, "submission_confirmed": True},
    {"success": True, "confirmation_evidence": [{"is_sufficient": False}]},
    {"success": False, "final_submit_attempted": False},
    None,
])
def test_ambiguous_browser_result_is_uncertain(result):
    assert _classify_browser_result(result) == "submission_uncertain"


def test_explicit_pre_submit_proof_allows_retry():
    assert _classify_browser_result({
        "success": False,
        "final_submit_attempted": False,
        "pre_submit_failure_verified": True,
    }) == "failed_pre_submit"


def test_sufficient_confirmation_evidence_is_required():
    assert _classify_browser_result({
        "success": True,
        "confirmation_evidence": [{"is_sufficient": True, "evidence_type": "success_banner"}],
    }) == "confirmed"
