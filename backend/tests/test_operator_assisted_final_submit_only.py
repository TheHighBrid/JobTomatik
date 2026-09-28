from app.models.application import ManualReviewReason
from app.services import operator_assisted_auto_submit as auto_submit
from app.tasks import operator_assisted


def test_only_final_submit_boundary_triggers_final_action():
    final = {
        "handoff_public_id": "handoff-final",
        "review_items": [
            {"reason_code": ManualReviewReason.operator_final_submit_required.value}
        ],
    }
    question = {
        "handoff_public_id": "handoff-question",
        "review_items": [{"reason_code": ManualReviewReason.ambiguous_question.value}],
    }
    captcha = {
        "handoff_public_id": "handoff-captcha",
        "review_items": [{"reason_code": ManualReviewReason.captcha_detected.value}],
    }

    assert operator_assisted._final_submit_handoff_id(final) == "handoff-final"
    assert operator_assisted._final_submit_handoff_id(question) == ""
    assert operator_assisted._final_submit_handoff_id(captcha) == ""


def test_final_boundary_requires_retained_handoff_id():
    result = {
        "review_items": [
            {"reason_code": ManualReviewReason.operator_final_submit_required.value}
        ]
    }
    assert operator_assisted._final_submit_handoff_id(result) == ""


def test_blocked_final_action_never_retries_or_claims_click():
    result = auto_submit._blocked("handoff-final", "captcha")
    assert result["requires_manual_review"] is True
    assert result["final_submit_clicked_by_jobtomatik"] is False
    assert result["automatic_retry_allowed"] is False
