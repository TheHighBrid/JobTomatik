import asyncio

from app.models.application import (
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
)
from app.services import operator_assisted_auto_submit as auto_submit
from app.tasks import operator_assisted as operator_task


def _final_boundary(handoff_public_id="handoff-final"):
    return {
        "success": False,
        "requires_manual_review": True,
        "handoff_public_id": handoff_public_id,
        "review_items": [
            {"reason_code": ManualReviewReason.operator_final_submit_required.value}
        ],
        "final_submit_clicked_by_jobtomatik": False,
    }


def test_non_final_review_boundary_never_enters_auto_submit(monkeypatch):
    result = {
        "success": False,
        "requires_manual_review": True,
        "handoff_public_id": "handoff-question",
        "review_items": [
            {"reason_code": ManualReviewReason.ambiguous_question.value}
        ],
    }

    def forbidden_run_async(_coro):
        raise AssertionError("auto-submit must not run for question/captcha review boundaries")

    monkeypatch.setattr(operator_task, "_run_async", forbidden_run_async)

    returned = operator_task._finish_retained_lever_boundary(17, dict(result))

    assert returned == result


def test_exact_final_boundary_runs_submit_only_after_retention(monkeypatch):
    calls = []

    async def fake_submit(application_id, handoff_public_id):
        calls.append((application_id, handoff_public_id))
        return {
            "submission_confirmed": True,
            "current_url": "https://jobs.lever.co/example/thanks",
            "confirmation_evidence": [{"is_sufficient": True}],
            "confirmation_detector": "lever_adapter_strict",
            "final_submit_clicked_by_jobtomatik": True,
            "final_submit_click_possible": True,
            "automatic_retry_allowed": False,
        }

    monkeypatch.setattr(auto_submit, "submit_retained_lever_final_action", fake_submit)
    monkeypatch.setattr(operator_task, "_reconcile_confirmed_submission", lambda *_args: True)

    result = operator_task._finish_retained_lever_boundary(23, _final_boundary())

    assert calls == [(23, "handoff-final")]
    assert result["success"] is True
    assert result["requires_manual_review"] is False
    assert result["submission_confirmed"] is True
    assert result["final_submit_clicked_by_jobtomatik"] is True
    assert result["application_status"] == ApplicationStatus.applied.value
    assert result["automation_state"] == ApplicationAutomationState.confirmed.value


def test_unconfirmed_click_moves_to_no_retry_review_state(monkeypatch):
    async def fake_submit(_application_id, _handoff_public_id):
        return {
            "submission_confirmed": False,
            "final_submit_clicked_by_jobtomatik": True,
            "final_submit_click_possible": True,
            "automatic_retry_allowed": False,
            "current_url": "https://jobs.lever.co/example/apply",
        }

    monkeypatch.setattr(auto_submit, "submit_retained_lever_final_action", fake_submit)
    monkeypatch.setattr(
        operator_task,
        "_record_unconfirmed_final_submit",
        lambda *_args: ApplicationAutomationState.submission_uncertain.value,
    )

    result = operator_task._finish_retained_lever_boundary(29, _final_boundary())

    assert result["success"] is False
    assert result["requires_manual_review"] is True
    assert result["submission_confirmed"] is False
    assert result["automatic_retry_allowed"] is False
    assert result["automation_state"] == ApplicationAutomationState.submission_uncertain.value


def test_submit_executor_is_async_contract():
    assert asyncio.iscoroutinefunction(auto_submit.submit_retained_lever_final_action)
