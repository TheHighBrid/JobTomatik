import pytest

from app.models.application import Application, ManualReviewReason, ManualReviewStatus, ManualReviewTask
from app.services.manual_review_shape import is_answer_policy_question_item, result_review_summary
from tests.conftest import TestingSessionLocal
from tests.test_misclassified_answer_policy_review_repair import _seed_review


ERROR = "No next-step or final-submit control was found."


def navigation_item():
    return {
        "reason_code": "unsupported_control",
        "summary": ERROR,
        "details": {"adapter": "lever", "step": 1, "fingerprint": "synthetic-form"},
    }


def test_flow_failure_is_not_a_missing_question():
    assert not is_answer_policy_question_item(navigation_item())
    assert result_review_summary([navigation_item()]) == ERROR
    # Historical field reviews may be missing only their readable descriptor.
    question = {"reason_code": "unsupported_control", "details": {"control_type": "radio"}}
    assert is_answer_policy_question_item(question)
    assert is_answer_policy_question_item({"reason_code": "ambiguous_question", "details": {}})
    assert not is_answer_policy_question_item({"reason_code": "operator_final_submit_required"})
    assert is_answer_policy_question_item(
        {"details": {"control_type": "radio"}},
        ManualReviewReason.unsupported_control,
    )


@pytest.mark.parametrize("nested_reason", [True, False])
def test_legacy_navigation_review_displays_actual_error_and_cannot_retire(auth_client, nested_reason):
    item = navigation_item()
    if not nested_reason:
        item.pop("reason_code")
    app_id, review_id = _seed_review(
        reason_code="unsupported_control",
        summary="1 application question(s) require an approved answer policy.",
        details={"questions": [item]},
    )
    response = auth_client.get(f"/api/applications/{app_id}")
    assert response.status_code == 200
    review = next(item for item in response.json()["manual_reviews"] if item["id"] == review_id)
    assert review["summary"] == ERROR
    assert review["answer_policy_question_count"] == 0
    assert review["application_step_blockers"] == [ERROR]
    with TestingSessionLocal() as db:
        # Reading the corrected display does not mutate historical records.
        assert db.get(ManualReviewTask, review_id).summary == "1 application question(s) require an approved answer policy."

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"] is False
    assert data["total_questions"] == 0
    assert data["satisfied_questions"] == 0
    assert data["fresh_reprepare_available"] is False
    assert data["remaining"][0]["reason"] == ERROR
    assert data["remaining"][0]["blocker_codes"] == ["application_step_review_required"]

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/retire-stale-for-reprepare"
    )
    assert response.status_code == 409
    with TestingSessionLocal() as db:
        review = db.get(ManualReviewTask, review_id)
        assert review.status == ManualReviewStatus.open.value
        assert review.summary == ERROR
        assert review.details["questions"] == [item]
        app = db.get(Application, app_id)
        assert app.automation_state == "needs_review"
        assert app.submission_attempt_count == 0


def test_new_navigation_review_keeps_original_summary(auth_client):
    from app.tasks.applications import _create_result_review_tasks

    app_id, _ = _seed_review(reason_code="ambiguous_question", summary="Earlier review", details={})
    with TestingSessionLocal() as db:
        app = db.get(Application, app_id)
        _create_result_review_tasks(
            db, app, {"review_items": [navigation_item()]}, "browser", app.application_target_url,
        )
        db.flush()
        review = db.query(ManualReviewTask).filter_by(application_id=app_id, reason_code="unsupported_control").one()
        assert review.summary == ERROR
        assert review.details["questions"] == [navigation_item()]


def test_mixed_review_does_not_retire_navigation_failure(auth_client):
    question = {"reason_code": "ambiguous_question", "details": {"control_type": "radio"}}
    app_id, review_id = _seed_review(
        reason_code="unsupported_control", summary="Old review",
        details={"questions": [question, navigation_item()]},
    )
    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_questions"] == 1
    assert len(data["remaining"]) == 2
    assert data["resolved"] is False
    assert data["fresh_reprepare_available"] is False
