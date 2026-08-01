from __future__ import annotations

from collections.abc import Mapping


FRAMEWORK_VERSION = "jobtomatik-opportunity-v1"
DIMENSION_WEIGHTS = {
    "north_star_alignment": 0.25,
    "cv_match": 0.15,
    "level": 0.15,
    "estimated_compensation": 0.10,
    "growth_trajectory": 0.10,
    "remote_quality": 0.05,
    "company_reputation": 0.05,
    "tech_stack_modernity": 0.05,
    "time_to_offer_speed": 0.05,
    "cultural_signals": 0.05,
}
RECOMMENDATION_THRESHOLDS = {
    "strong_apply": 4.0,
    "apply": 3.4,
    "hold": 2.8,
}


def calculate_weighted_score(scores: Mapping[str, float]) -> float:
    missing = set(DIMENSION_WEIGHTS) - set(scores)
    unexpected = set(scores) - set(DIMENSION_WEIGHTS)
    if missing or unexpected:
        raise ValueError(
            "Evaluation dimensions must exactly match the framework: "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )

    weighted = 0.0
    for dimension, weight in DIMENSION_WEIGHTS.items():
        value = float(scores[dimension])
        if not 1.0 <= value <= 5.0:
            raise ValueError(f"{dimension} must be between 1 and 5")
        weighted += value * weight
    return round(weighted, 3)


def classify_recommendation(
    weighted_score: float,
    *,
    hard_blockers: list[str] | None = None,
    legitimacy_status: str = "unknown",
) -> str:
    if hard_blockers or legitimacy_status == "blocked":
        return "do_not_apply"
    if legitimacy_status == "needs_review":
        return "review_first"
    if weighted_score >= RECOMMENDATION_THRESHOLDS["strong_apply"]:
        return "strong_apply"
    if weighted_score >= RECOMMENDATION_THRESHOLDS["apply"]:
        return "apply"
    if weighted_score >= RECOMMENDATION_THRESHOLDS["hold"]:
        return "hold"
    return "skip"


def evaluate_opportunity(
    scores: Mapping[str, float],
    *,
    hard_blockers: list[str] | None = None,
    legitimacy_status: str = "unknown",
) -> dict[str, object]:
    normalized_scores = {key: float(value) for key, value in scores.items()}
    weighted_score = calculate_weighted_score(normalized_scores)
    blockers = [item.strip() for item in (hard_blockers or []) if item.strip()]
    recommendation = classify_recommendation(
        weighted_score,
        hard_blockers=blockers,
        legitimacy_status=legitimacy_status,
    )
    return {
        "framework_version": FRAMEWORK_VERSION,
        "weighted_score": weighted_score,
        "recommendation": recommendation,
        "dimension_scores": normalized_scores,
        "hard_blockers": blockers,
        "legitimacy_status": legitimacy_status,
    }


def framework_manifest() -> dict[str, object]:
    return {
        "framework_version": FRAMEWORK_VERSION,
        "dimensions": DIMENSION_WEIGHTS,
        "score_range": {"minimum": 1.0, "maximum": 5.0},
        "recommendation_thresholds": RECOMMENDATION_THRESHOLDS,
        "legitimacy_is_separate": True,
        "hard_blockers_override_score": True,
    }
