from app.models.application import ManualReviewTask
from tests.conftest import TestingSessionLocal
from tests.test_manual_review_policy_revalidation import _seed_caseware_review


def test_answer_vault_recheck_persists_question_visibility_after_refresh(auth_client):
    app_id, review_id, _ = _seed_caseware_review()

    response = auth_client.post(
        f"/api/applications/{app_id}/manual-reviews/{review_id}/revalidate-answer-policies"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["resolved"] is False
    assert result["remaining"]

    db = TestingSessionLocal()
    try:
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        assert "Are you physically located in Canada" in review.summary
        persisted = (review.details or {}).get("last_policy_revalidation") or {}
        assert persisted["review_id"] == review_id
        assert persisted["remaining"][0]["canonical_key"] == "work_authorization"
        assert "Are you physically located in Canada" in persisted["remaining"][0]["descriptor"]
    finally:
        db.close()
