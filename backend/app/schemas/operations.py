from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class OperationsPipelineItem(BaseModel):
    application_id: int
    job_id: int
    title: str
    company: str
    location: str | None = None
    status: str
    automation_state: str
    application_target_status: str
    applied_at: datetime | None = None
    interview_at: datetime | None = None
    offer_received_at: datetime | None = None
    salary_offered: int | None = None
    latest_event_type: str | None = None
    latest_event_at: datetime | None = None
    open_review_count: int = 0
    followup_count: int = 0


class OperationsPipelineColumn(BaseModel):
    status: str
    label: str
    count: int
    items: list[OperationsPipelineItem] = Field(default_factory=list)


class OperationsTimelineItem(BaseModel):
    kind: Literal["application_event", "recruiter_interaction"]
    occurred_at: datetime
    title: str
    summary: str | None = None
    application_id: int | None = None
    recruiter_contact_id: int | None = None
    job_id: int | None = None
    company: str | None = None
    event_type: str
    from_state: str | None = None
    to_state: str | None = None
    action_url: str | None = None


class OperationsEvaluationItem(BaseModel):
    evaluation_id: int
    job_id: int | None = None
    application_id: int | None = None
    title: str
    company: str
    weighted_score: float
    recommendation: str
    legitimacy_status: str
    hard_blockers: list[str] = Field(default_factory=list)
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    created_at: datetime
    action_url: str | None = None


class OperationsAgendaItem(BaseModel):
    item_type: Literal[
        "interview",
        "recruiter_followup",
        "followup_draft",
        "followup_delivery",
        "manual_review",
    ]
    scheduled_at: datetime
    priority: Literal["high", "medium", "low"]
    title: str
    subtitle: str | None = None
    status: str
    application_id: int | None = None
    recruiter_contact_id: int | None = None
    followup_id: int | None = None
    action_url: str | None = None
    overdue: bool = False


class OperationsWorkspaceOut(BaseModel):
    generated_at: datetime
    agenda_window_start: datetime
    agenda_window_end: datetime
    summary: dict[str, int]
    pipeline: list[OperationsPipelineColumn] = Field(default_factory=list)
    timeline: list[OperationsTimelineItem] = Field(default_factory=list)
    evaluations: list[OperationsEvaluationItem] = Field(default_factory=list)
    agenda: list[OperationsAgendaItem] = Field(default_factory=list)


class CareerMemoryCorrection(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.content is None and self.confidence is None and self.is_active is None:
            raise ValueError("At least one memory correction field is required")
        return self


class KnowledgeEdgeListItem(BaseModel):
    id: int
    from_node_id: int
    to_node_id: int
    relation: str
    weight: float
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
