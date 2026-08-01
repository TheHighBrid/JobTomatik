from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvaluationDimensions(BaseModel):
    north_star_alignment: float = Field(ge=1.0, le=5.0)
    cv_match: float = Field(ge=1.0, le=5.0)
    level: float = Field(ge=1.0, le=5.0)
    estimated_compensation: float = Field(ge=1.0, le=5.0)
    growth_trajectory: float = Field(ge=1.0, le=5.0)
    remote_quality: float = Field(ge=1.0, le=5.0)
    company_reputation: float = Field(ge=1.0, le=5.0)
    tech_stack_modernity: float = Field(ge=1.0, le=5.0)
    time_to_offer_speed: float = Field(ge=1.0, le=5.0)
    cultural_signals: float = Field(ge=1.0, le=5.0)


class OpportunityEvaluationCreate(BaseModel):
    job_id: int | None = None
    application_id: int | None = None
    dimension_scores: EvaluationDimensions
    analysis_blocks: dict[str, Any] = Field(default_factory=dict)
    legitimacy_status: Literal[
        "unknown",
        "likely_legitimate",
        "needs_review",
        "blocked",
    ] = "unknown"
    hard_blockers: list[str] = Field(default_factory=list)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)


class OpportunityEvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    job_id: int | None = None
    application_id: int | None = None
    framework_version: str
    status: str
    recommendation: str
    weighted_score: float
    dimension_scores: dict[str, float]
    analysis_blocks: dict[str, Any]
    legitimacy_status: str
    hard_blockers: list[str]
    source_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None = None


class EvaluationFrameworkOut(BaseModel):
    framework_version: str
    dimensions: dict[str, float]
    score_range: dict[str, float]
    recommendation_thresholds: dict[str, float]
    legitimacy_is_separate: bool
    hard_blockers_override_score: bool
