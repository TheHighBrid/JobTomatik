from app.services.opportunity_evaluation import (
    calculate_weighted_score,
    classify_recommendation,
    evaluate_opportunity,
)


STRONG_SCORES = {
    "north_star_alignment": 5,
    "cv_match": 4.5,
    "level": 4,
    "estimated_compensation": 4,
    "growth_trajectory": 4.5,
    "remote_quality": 4,
    "company_reputation": 4,
    "tech_stack_modernity": 3.5,
    "time_to_offer_speed": 3,
    "cultural_signals": 4,
}


def test_weighted_score_uses_declared_dimensions():
    score = calculate_weighted_score(STRONG_SCORES)

    assert score == 4.375
    assert classify_recommendation(score) == "strong_apply"


def test_legitimacy_and_hard_blockers_override_score():
    score = calculate_weighted_score(STRONG_SCORES)

    assert classify_recommendation(score, legitimacy_status="needs_review") == "review_first"
    assert classify_recommendation(score, hard_blockers=["work authorization mismatch"]) == "do_not_apply"
    assert classify_recommendation(score, legitimacy_status="blocked") == "do_not_apply"


def test_evaluation_api_persists_auditable_result(auth_client):
    response = auth_client.post(
        "/api/evaluations",
        json={
            "dimension_scores": STRONG_SCORES,
            "analysis_blocks": {
                "A": {"role_summary": "Fraud investigation role"},
                "B": {"match": "Strong banking and investigation overlap"},
                "G": {"legitimacy": "Official employer posting"},
            },
            "legitimacy_status": "likely_legitimate",
            "source_snapshot": {"url": "https://example.test/jobs/123"},
        },
    )

    assert response.status_code == 201
    evaluation = response.json()
    assert evaluation["weighted_score"] == 4.375
    assert evaluation["recommendation"] == "strong_apply"
    assert evaluation["legitimacy_status"] == "likely_legitimate"
    assert evaluation["analysis_blocks"]["G"]["legitimacy"] == "Official employer posting"

    list_response = auth_client.get("/api/evaluations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    framework_response = auth_client.get("/api/evaluations/framework")
    assert framework_response.status_code == 200
    framework = framework_response.json()
    assert sum(framework["dimensions"].values()) == 1.0
    assert framework["legitimacy_is_separate"] is True
    assert framework["hard_blockers_override_score"] is True


def test_evaluate_opportunity_normalizes_blockers():
    result = evaluate_opportunity(
        STRONG_SCORES,
        hard_blockers=["", "  unsupported location  "],
        legitimacy_status="likely_legitimate",
    )

    assert result["hard_blockers"] == ["unsupported location"]
    assert result["recommendation"] == "do_not_apply"
