"""JT5 browser-result classification must never infer a safe retry from silence."""
import asyncio

import pytest
from app.services.form_filler_v3 import fill_and_submit_application as fill_real_form

from app.tasks.jt5_execution import (
    _classify_browser_result,
    normalize_jt5_browser_result,
)


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


def test_normalize_maps_submit_clicked_log_to_final_submit_attempted():
    normalized = normalize_jt5_browser_result({
        "success": False,
        "error": "no confirmation",
        "log": [{"action": "ats_submit_clicked"}],
    })
    assert normalized["final_submit_attempted"] is True
    assert _classify_browser_result(normalized) == "submission_uncertain"


def test_normalize_pre_browser_invalid_url_is_retryable():
    normalized = normalize_jt5_browser_result({
        "success": False,
        "error": "Invalid or unsupported job URL",
        "log": [],
    })
    assert normalized["final_submit_attempted"] is False
    assert normalized["pre_submit_failure_verified"] is True
    assert _classify_browser_result(normalized) == "failed_pre_submit"


@pytest.mark.parametrize("job_url", [
    "http://127.0.0.1:8000/private-job",
    "https://example.com/jobs/placeholder-1",
])
def test_real_form_filler_pre_browser_rejections_classify_as_failed_pre_submit(job_url):
    result = asyncio.run(fill_real_form(job_url, {}, "", "", dry_run=False))

    assert result["ats_adapter"] == "generic"
    assert _classify_browser_result(result) == "failed_pre_submit"


@pytest.mark.parametrize("post_launch_signal", [
    {"log": [{"action": "navigate"}]},
    {"ats_adapter": "greenhouse"},
    {"fields_filled_count": 1},
    {"screenshot": "capture.png"},
    {"handoff_required": True},
    {"submit_clicked": True},
    {"browser_started": True},
])
def test_pre_browser_error_string_after_browser_activity_stays_uncertain(post_launch_signal):
    result = {
        "success": False,
        "error": "Placeholder URL; manual application required",
        "ats_adapter": "generic",
        "final_submit_attempted": False,
        "pre_submit_failure_verified": True,
        **post_launch_signal,
    }

    normalized = normalize_jt5_browser_result(result)
    assert normalized["pre_submit_failure_verified"] is False
    assert _classify_browser_result(normalized) == "submission_uncertain"


def test_normalize_captcha_after_navigate_stays_uncertain():
    normalized = normalize_jt5_browser_result({
        "success": False,
        "error": "CAPTCHA detected",
        "requires_manual_review": True,
        "submit_clicked": False,
        "log": [{"action": "navigate"}, {"action": "captcha_detected"}],
        "ats_adapter": "greenhouse",
    })
    assert normalized["final_submit_attempted"] is False
    assert normalized["pre_submit_failure_verified"] is False
    assert _classify_browser_result(normalized) == "submission_uncertain"


def test_normalize_submit_clicked_flag_marks_final_action():
    normalized = normalize_jt5_browser_result({
        "success": False,
        "submit_clicked": True,
        "confirmation_evidence": [],
        "log": [],
    })
    assert normalized["final_submit_attempted"] is True
    assert _classify_browser_result(normalized) == "submission_uncertain"


@pytest.mark.parametrize("final_action", [
    {"submit_clicked": True},
    {"log": [{"action": "ats_submit_clicked"}]},
    {"final_submit_attempted": True},
])
def test_contradictory_pre_submit_proof_never_allows_retry(final_action):
    result = {
        "success": False,
        "error": "timeout",
        "pre_submit_failure_verified": True,
        "final_submit_attempted": False,
        **final_action,
    }
    normalized = normalize_jt5_browser_result(result)
    assert normalized["pre_submit_failure_verified"] is False
    assert _classify_browser_result(normalized) == "submission_uncertain"
